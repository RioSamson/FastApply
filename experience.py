"""Fill Oracle's inline experience editor using the saved employment history."""
import calendar
import re
import time

from core import norm


def desired_fields(row):
    values = {
        'employerName': row['company'],
        'jobTitle': row['title'],
        'countryCode': row.get('country'),
        'employerCity': row.get('city'),
        'achievements': row.get('description'),
        'responsibilities': row.get('description'),
        'currentJobFlag': row.get('current', row.get('end_date') == ''),
        'Internal': row.get('internal'),
    }
    for key, date in (('startDate', row.get('start_date')), ('endDate', row.get('end_date'))):
        if date and re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])(?:-\d{2})?', date):
            year, month = date.split('-')[:2]
            values['year-' + key] = year
            values['month-' + key] = calendar.month_name[int(month)]
    return values


def matches_title(cards, title):
    return [card for card in cards if norm(card['title']) == norm(title)]


def fill_experience(run, snapshot, page, rows):
    """Save each role separately and confirm the saved card before moving on."""
    filled, problems = [], []
    url = page['url']

    def refresh():
        time.sleep(.25)
        result = snapshot()
        if not result or result['url'] != url or result.get('experience') is None:
            return None
        return result

    def editor_op(action, **payload):
        return run(action, {'url': url, **payload})

    rows = [row for row in rows if row.get('title') and row.get('company')]
    if page['experience']['editor']:
        existing = {field['key']:field['value'] for field in page['experience']['fields']}
        matches = [row for row in rows if norm(existing.get('jobTitle') or '') == norm(row['title'])
                   and (not existing.get('employerName') or norm(existing['employerName']) == norm(row['company']))]
        if len(matches) != 1:
            return filled, ['Finish or cancel the open Experience editor, then resume FastApply.']
        rows = matches + [row for row in rows if row is not matches[0]]
    for row in rows:
        title, company = row['title'], row['company']
        cards = matches_title(page['experience']['cards'], title)
        if len(cards) > 1 or (cards and cards[0]['subtitle'] and
                              not norm(cards[0]['subtitle']).startswith(norm(company)+' ') and
                              norm(cards[0]['subtitle']) != norm(company) and
                              not re.match(r'^\d{4}-', cards[0]['subtitle'])):
            problems.append(f'{title}: check the existing employer or duplicate entries in Safari.')
            continue
        if not cards and not {'year-startDate', 'month-startDate'} <= desired_fields(row).keys():
            problems.append(f'{title}: add a start month and year to the FastApply profile.')
            continue
        was_open = page['experience']['editor']
        if not was_open:
            result = editor_op('experience-open', id=cards[0]['id'] if cards else None)
            if not result['filled']:
                problems.append(f'{title}: could not open the Experience editor.')
                break
            page = refresh()
            if not page or not page['experience']['editor']:
                problems.append(f'{title}: the Experience editor did not load.')
                break
        changed = False
        failed = False
        desired = desired_fields(row)
        attempted = set()
        while page:
            fields = page['experience']['fields']
            answers = []
            for field in fields:
                key = field['key']
                value = desired.get(key)
                if field['value'] or value is None or key in attempted:
                    continue
                if field['type'] == 'checkbox' and value is False:
                    continue
                if field['type'] == 'radio' and (field['groupAnswered'] or field['label'] != ('Yes' if value else 'No')):
                    continue
                answers.append((key, field, value))
            if not answers:
                break
            # Form controls can be recreated after a choice. Re-read field IDs before each edit.
            key, field, value = answers[0]
            attempted.add(key)
            answer = {'id': field['id'], 'value': value, 'checked': field['type'] in ('checkbox', 'radio')}
            if field['type'] == 'combobox':
                run('custom-open', answer)
                for _ in range(12):
                    time.sleep(.2)
                    result = run('custom-select', answer)
                    if result['filled']:
                        break
            else:
                result = run('fill', {'answers': [answer]})
            page = refresh()
            accepted = page and any(
                f['key'] == key and f['value'] and
                (f['type'] == 'checkbox' or f['value'] == str(('Yes' if value else 'No') if field['type']=='radio' else value))
                for f in page['experience']['fields'])
            if not result['filled'] and not accepted:
                problems.append(f'{title}: could not select or enter {field["label"]}.')
                failed = True
                break
            changed = True

        if not page:
            problems.append(f'{title}: the experience page changed before saving.')
            break
        fields = page['experience']['fields']
        missing = [field['label'] for field in fields
                   if field['required'] and not field['value'] and not field['groupAnswered']]
        if missing or failed:
            problems.append(f'{title}: verify the Experience editor in Safari.')
            break
        if not cards and not was_open and not changed:
            problems.append(f'{title}: the blank editor did not accept the saved role.')
            break
        editor_op('experience-save' if changed or was_open else 'experience-cancel')
        for _ in range(15):
            page = refresh()
            if not page or not page['experience']['editor']:
                break
        verified = page and matches_title(page['experience']['cards'], title)
        if not verified or page['experience']['editor'] or len(verified)!=1 or verified[0]['invalid']:
            problems.append(f'{title}: Oracle did not confirm a complete saved experience.')
            break
        if changed:
            filled.append(f'Experience saved: {title}')
    return filled, problems
