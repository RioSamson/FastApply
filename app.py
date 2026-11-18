#!/usr/bin/env python3
"""Single-user local application. Python 3.10+, no third-party dependencies."""
import argparse, json, os, pathlib, secrets, threading, time, urllib.parse, urllib.request, http.server, signal, sys, fcntl
from core import extract, plan, resume, safe_url, simplify_target, embedded_application, validate_resume, validate_profile, answer_key, learnable, preferred_location
from experience import fill_experience
from safari import Safari, SafariError

ROOT=pathlib.Path(__file__).resolve().parent
ENGINE=(ROOT/'engine.js').read_text()

def atomic(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.chmod(0o600);tmp.replace(path)

class Store:
    def __init__(self,path):
        self.path=path;path.mkdir(parents=True,exist_ok=True);path.chmod(0o700)
        (path/'cache').mkdir(exist_ok=True);(path/'cache').chmod(0o700)
        self.lock=threading.RLock()
        self.state=json.loads((path/'state.json').read_text()) if (path/'state.json').exists() else {'jobs':[],'mode':'paused'}
        self.state['mode']='paused'
        for j in self.state['jobs']:
            if j['status'] in ('Opening','Filling','Queued'):
                j['status']='Needs input';j['concerns']=['Interrupted or restarted. Resume explicitly; existing Safari window will be reused.']
        if not (path/'profile.json').exists():atomic(path/'profile.json',json.loads((ROOT/'profile.example.json').read_text()))
        self.save()
    def save(self):
        with self.lock:atomic(self.path/'state.json',self.state)
    def profile(self):return json.loads((self.path/'profile.json').read_text())
    def update(self,j,**kwargs):
        with self.lock:j.update(kwargs);self.save()

def remember_contact_fields(store,job,snapshot,profile):
    # Learn aliases only from a human edit matching one unique saved contact fact.
    # Store the profile key, so changing the profile also changes future answers.
    from core import LEGAL,SENSITIVE,norm
    keys=('name','first_name','last_name','email','phone','linkedin','github','portfolio')
    scope=urllib.parse.urlsplit(snapshot['url']).hostname+'|'+job['company'].casefold()
    memory=store.state.setdefault('contact_aliases',{}).setdefault(scope,{})
    profile['answers']=dict(profile.get('answers',{}))
    changed=False
    for field in snapshot['fields']:
        label=norm(field['label'])
        if not label or LEGAL.search(label) or SENSITIVE.search(label):continue
        if field.get('manual') and field.get('value'):
            matches=[k for k in keys if profile.get(k)==field['value']]
            if len(matches)==1 and memory.get(label)!=matches[0]:
                memory[label]=matches[0]
                changed=True
        # Explicit user edits to factual education questions can be reused for this employer.
        education_labels={'where do you study','where dodid you study','institution','what was the majorfield of study for your degrees','what degree do you did you study'}
        if label in education_labels:
            learned=store.state.setdefault('education_answers',{}).setdefault(scope,{})
            if field.get('manual') and field.get('value') and learned.get(label)!=field['value']:
                learned[label]=field['value']
                changed=True
            if learned.get(label):profile['answers'].setdefault(label,{'value':learned[label]})
        if label in memory and profile.get(memory[label]):
            profile['answers'].setdefault(label,{'value':profile[memory[label]]})
    if changed:store.save()

def answer_scope(job):
    return job['company'].casefold()+'|'+(urllib.parse.urlsplit(job.get('final_url') or '').hostname or '')

def reusable_scope(key, entry, share, job):
    if key=='are you at least 18 years old' or (key in share and learnable(entry['label'])):
        return 'shared'
    return answer_scope(job)


def scan_answers(fields):
    candidates={}
    for field in fields:
        kind=field['type']
        label=(field.get('question') if kind=='radio' else field['label']) or ''
        value=field.get('selectedLabel') or (field['label'] if kind=='radio' else field['value'])
        allowed={'text','textarea','select-one','combobox','radio','url','tel','email','date','number'}
        if field.get('invalid') or not label or not field['value'] or not value or kind not in allowed or not learnable(label):
            continue
        key=answer_key(label)
        if key=='are you at least 18 years old' and value.strip().casefold() not in ('yes','no'):
            continue
        entry={'label':label,'value':str(value)[:4000]}
        if key not in candidates:candidates[key]=entry
        elif candidates[key]!=entry:candidates[key]=None
    return {key:value for key,value in candidates.items() if value is not None}

class Runner:
    def __init__(self,store,fixture=False):
        self.store=store;self.browser=Safari();self.fixture=fixture
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def js(self,j,op,payload=None):
        return self.browser.evaluate(j['window'],ENGINE.replace('__OP__',json.dumps(op)).replace('__PAYLOAD__',json.dumps(payload or {})))
    def checkpoint(self,j):
        with self.store.lock:
            if j not in self.store.state['jobs']:return False
            if self.store.state['mode']!='running':
                if j['status'] in ('Opening','Filling'):self.store.update(j,status='Needs input',concerns=['Batch paused/cancelled. Use Resume job to continue in its existing window.'])
                return False
        return True
    def loop(self):
        while True:
            with self.store.lock:
                job=next((j for j in self.store.state['jobs'] if j['status']=='Queued' and not j.get('manual')),None) if self.store.state['mode']=='running' else None
                if job:self.store.update(job,status='Opening')
            if job:
                try:self.prepare(job)
                except (SafariError,ValueError,OSError) as e:self.store.update(job,status='Needs input',concerns=[str(e) if isinstance(e,(SafariError,ValueError)) else 'Local file or system access failed; check profile and resume path.'])
                except Exception:self.store.update(job,status='Failed',concerns=['Unexpected preparation error. Existing window retained; retry after checking configuration.'])
            else:time.sleep(.2)
    def snapshot(self,j):
        for _ in range(20):
            if not self.checkpoint(j):return None
            s=self.js(j,'inspect')
            if s and s.get('ready')=='complete' and (s.get('text') or s.get('fields')):return s
            time.sleep(.3)
        raise ValueError('Page did not finish loading. Inspect Safari and resume this job.')
    def prepare(self,j):
        if not self.checkpoint(j):return
        if j.get('window'):
            # Require exact previously observed URL; a user-changed tab is never overwritten.
            try:current=self.browser.location(j['window'])
            except SafariError:raise ValueError('Saved Safari window is closed. Use Reopen job explicitly to create a replacement.')
            if current not in (j['original_url'],j.get('final_url'),j.get('last_url')):
                # Explicit resume allows user-driven steps on the same employer origin.
                old=j.get('final_url') or j.get('last_url') or j['original_url']
                greenhouse_return=(urllib.parse.urlsplit(current).hostname in ('job-boards.greenhouse.io','boards.greenhouse.io') and urllib.parse.urlsplit(current).path=='/embed/job_app' and urllib.parse.parse_qs(urllib.parse.urlsplit(old).query).get('gh_jid',[None])[0] in urllib.parse.parse_qs(urllib.parse.urlsplit(current).query).get('token',[]))
                if urllib.parse.urlsplit(current).netloc!=urllib.parse.urlsplit(old).netloc and not greenhouse_return:
                    raise ValueError('Saved Safari window has navigated to another site. Verify it, or reopen this job explicitly.')
        else:
            if not safe_url(j['original_url'],self.fixture):raise ValueError('Unsafe or unsupported listing URL.')
            # Persist before automation, and window identity immediately after creation.
            self.store.update(j,opening_pending=True)
            w=self.browser.open(j['original_url']);self.store.update(j,window=w,opening_pending=False,last_url=j['original_url'])
        entry_pages=set()
        for hop in range(10):
            s=self.snapshot(j)
            if s is None:return
            self.store.update(j,last_url=s['url'])
            if not safe_url(s['url'],self.fixture):raise ValueError('Redirect reached an unsupported address. Inspect Safari manually.')
            t=s['text'];host=urllib.parse.urlsplit(s['url']).hostname
            if host not in ('simplify.jobs','www.simplify.jobs'):self.store.update(j,final_url=s['url'])
            if __import__('re').search(r'(job (?:is |has )?(?:no longer available|expired|closed)|position (?:has been filled|is closed)|listing expired)',t,__import__('re').I):
                self.store.update(j,status='Unavailable',concerns=['Listing is expired or closed.']);return
            if any(f['type']=='password' for f in s['fields']) or __import__('re').search(r'captcha|verify you are human|sign in to (?:apply|continue)|log in to (?:apply|continue)',t,__import__('re').I):
                self.store.update(j,status='Needs input',concerns=['Login or access challenge. Complete it in Safari, then Resume job.']);return
            target=simplify_target(s,j['original_url'])
            if target:
                if s['simplify'].get('active') is False:
                    self.store.update(j,status='Unavailable',concerns=['Simplify marks this listing inactive.']);return
                locations=s['simplify'].get('locations',[])
                notes=['Listing location: '+str(x) for x in locations]
                preferences=self.store.profile().get('availability',{}).get('location_preferences',[])
                matches=[match for location in locations if (match:=preferred_location(location,preferences))]
                if matches:
                    rank,place=min(matches)
                    notes.append(f'Location preference #{rank}: {place}')
                notes+=['Eligibility requirement: '+str(x) for x in s['simplify'].get('requirements',[]) if __import__('re').search(r'must|graduate|student|citizen|authoriz|sponsor|eligible',str(x),__import__('re').I)]
                self.store.update(j,listing_concerns=notes)
                if not self.checkpoint(j):return
                self.browser.navigate(j['window'],target);time.sleep(.8);continue
            embedded=embedded_application(s)
            if embedded:
                if not self.checkpoint(j):return
                self.browser.navigate(j['window'],embedded);time.sleep(.8);continue
            if s.get('entry') and s['url'] not in entry_pages:
                entry_pages.add(s['url'])
                if not self.checkpoint(j):return
                self.js(j,'entry',{'url':s['url']})
                time.sleep(1)
                continue
            if s['fields'] or s.get('experience') or s.get('cards') or '/apply/section/' in s['url']:break
            candidates=[l for l in s['links'] if __import__('re').fullmatch(r'apply(?: here| now| for (?:this )?(?:job|position)| on (?:company|employer)(?: website)?)?|apply externally',l['text'],__import__('re').I) and safe_url(l['url'],self.fixture)]
            candidates=list({l['url']:l for l in candidates}.values())
            if len(candidates)!=1:
                self.store.update(j,status='Needs input',concerns=['No unique navigational Apply link. Open the employer form manually, then resume. Buttons are not clicked automatically.']);return
            if not self.checkpoint(j):return
            self.browser.navigate(j['window'],candidates[0]['url']);time.sleep(.6)
        else:raise ValueError('Too many navigation steps; inspect the Safari window.')
        if host in ('simplify.jobs','www.simplify.jobs'):
            # A newsletter/search field must not receive personal profile data.
            candidates=[l for l in s['links'] if l['text'].lower().startswith('apply') and safe_url(l['url'],self.fixture) and urllib.parse.urlsplit(l['url']).hostname not in ('simplify.jobs','www.simplify.jobs')]
            if len(candidates)!=1:raise ValueError('Simplify has no unique external Apply link. Open employer application manually.')
            self.browser.navigate(j['window'],candidates[0]['url']);time.sleep(.6);s=self.snapshot(j)
            if not s:return
        self.store.update(j,status='Filling',final_url=s['url'])
        profile=self.store.profile();filled=list(j.get('filled',[]));concerns=list(j.get('listing_concerns',[]));upload=None
        if len(profile.get('education',[]))==1:
            education=profile['education'][0]
            answers=profile.setdefault('answers',{})
            for question,key in [('where dodid you study','school'),('institution','school'),('what was the majorfield of study for your degrees','field'),('what degree do you did you study','degree')]:
                if education.get(key):answers.setdefault(question,{'value':education[key]})
        if profile.get('availability',{}).get('start_date'):
            profile.setdefault('answers',{}).setdefault('when would you be available to start',{'value':profile['availability']['start_date']})
        protected=set(j.get('protected_fields',[]))
        attempted_choices=set()
        attempted_cards=set()
        editing=None
        experience_checked=False
        experience_problems=[]
        for step in range(32):
            if not self.checkpoint(j):return
            s=self.snapshot(j)
            if not s:return
            # Country is explicitly configured per job; never inferred from address or education.
            if any(f['type']=='password' for f in s['fields']) or __import__('re').search(r'captcha|verify you are human|sign in to (?:apply|continue)|log in to (?:apply|continue)',s['text'],__import__('re').I):
                self.store.update(j,status='Needs input',concerns=['Complete login or access challenge in Safari, then resume.']);return
            if s.get('experience') is not None and not experience_checked:
                experience_checked=True
                saved, experience_problems=fill_experience(
                    lambda op, payload: self.js(j,op,payload),
                    lambda: self.snapshot(j), s, profile.get('employment',[]))
                filled.extend(saved)
                if not self.checkpoint(j):return
                if experience_problems:
                    self.store.update(j,status='Needs input',missing=experience_problems,concerns=concerns,filled=list(dict.fromkeys(filled)))
                    return
                continue
            def signature(f):return s['url'].split('#')[0]+'|'+f.get('section','')+'|'+str(f.get('sectionIndex',0))+'|'+f['label']
            if s.get('locationNeeded'):
                address=profile.get('address',{})
                region=address.get('region')
                if address.get('country')=='Canada' and region=='BC':region='British Columbia'
                parts=[address.get('city'),region,address.get('country')]
                if all(parts):
                    location={'value':', '.join(parts)}
                    self.js(j,'location-search',location)
                    for _ in range(10):
                        time.sleep(.2)
                        selection=self.js(j,'location-select',location)
                        if selection['filled']:
                            filled.extend(selection['filled'])
                            break
                    s=self.snapshot(j)
                    if not s:return
            if not self.checkpoint(j):return
            if any(f['type']=='checkbox' and not f['value'] and answer_key(f['label'])=='i agree with the terms and conditions' for f in s['fields']):
                agreement=self.js(j,'accept-terms',{'url':s['url']})
                filled.extend(agreement['filled'])
                concerns.extend(agreement['issues'])
                s=self.snapshot(j)
                if not s:return
            for scope in (answer_scope(j),'shared'):
                for label,saved in self.store.state.get('learned_answers',{}).get(scope,{}).items():
                    profile.setdefault('answers',{}).setdefault(label,saved)
            remember_contact_fields(self.store,j,s,profile)
            if not editing:
                for card in s.get('cards',[]):
                    if card['id'] in attempted_cards:continue
                    attempted_cards.add(card['id'])
                    jobs=[r for r in profile.get('employment',[]) if r.get('title')==card['title'] and r.get('company')]
                    schools=[r for r in profile.get('education',[]) if r.get('school') and card['subtitle'].startswith(r['school']+' ') and r.get('degree')]
                    if len(jobs)==1:
                        editing={'Employer Name':jobs[0]['company']}
                    elif len(schools)==1:
                        row=schools[0]
                        degree="Bachelor's Degree" if row['degree'].lower().startswith('bachelor of ') else row['degree']
                        editing={'Degree':degree,'Area of Study':row.get('field')}
                    if editing:
                        self.js(j,'edit-card',{'id':card['id']})
                        time.sleep(.25)
                        break
                if editing:continue
            p=plan([f for f in s['fields'] if not f['value'] or signature(f) not in protected],profile,j.get('country'))
            if editing:
                p['answers']=[{'id':f['id'],'value':editing[f['label']],'custom':f['type']=='combobox'}
                              for f in s['fields'] if editing.get(f['label']) and not f['value']]
                if not p['answers']:
                    if any(f['label'] in editing for f in s['fields']) and all(not f['required'] or f['value'] for f in s['fields']):
                        self.js(j,'save-card',{'url':s['url']})
                        time.sleep(.25)
                        editing=None
                        continue
            result=self.js(j,'fill',{'answers':[a for a in p['answers'] if not a.get('custom')]})
            filled.extend(result['filled']);concerns.extend(result['issues'])
            fields_by_id={f['id']:f for f in s['fields']}
            for answer in p['answers']:
                if not answer.get('custom'):continue
                key=(signature(fields_by_id[answer['id']]),str(answer['value']))
                if key in attempted_choices:continue
                attempted_choices.add(key)
                self.js(j,'custom-open',answer)
                for attempt in range(12):
                    time.sleep(.2)
                    cr=self.js(j,'custom-select',answer)
                    if cr['filled']:break
                filled.extend(cr['filled']);concerns.extend(cr['issues'])
                time.sleep(.25)
                break
            else:
                answer=None
            if editing and result['filled']:continue
            if answer is not None:continue  # Parent dropdowns can replace the remaining fields.
            upload_fields=[f for f in s['fields'] if f['type']=='file' and __import__('re').search(r'resume|\bcv\b',f['label'],__import__('re').I)]
            for f in upload_fields:
                if not self.checkpoint(j):return
                if not f['value'] and signature(f) not in protected:
                    try:
                        upload=resume(profile,self.store.path/'cache');result=self.js(j,'upload',dict(upload,id=f['id']));concerns.extend(result['issues']);filled.extend(result['filled'])
                    except (ValueError,OSError) as e:concerns.append(str(e) if isinstance(e,ValueError) else 'Cannot read resume file; configure a readable local PDF/DOCX.')
            time.sleep(.35);s=self.snapshot(j)
            if not s:return
            for _ in range(15):
                if 'Parsing the résumé' not in s['text']:break
                time.sleep(.4)
                s=self.snapshot(j)
                if not s:return
            missing=[]
            for f in s['fields']:
                if (f['required'] and not f['value'] and f['type']!='radio') or (f.get('invalid') and (f['required'] or f['value'])):missing.append(f['label']+(': '+f['validation'] if f.get('validation') else ': required answer missing'))
                if f.get('ashbyQuestion') and not f['value']:missing.append(f['label']+': review written question')
                if f['type']=='combobox' and f['required'] and not f['value']:missing.append(f['label']+': verify custom selection manually')
                if f['type']=='file' and f['required'] and not f['value'] and not __import__('re').search(r'resume|\bcv\b',f['label'],__import__('re').I):missing.append((f['label'] or 'Document upload')+': unrecognized upload control; verify document requirement manually')
                if f['type']=='file' and f['value']:
                    # An accepted/uploaded receipt mentioning the document is needed, not only input.files.
                    receipt=any(f['value'] in line and __import__('re').search(r'accepted|uploaded|upload complete|successfully attached',line,__import__('re').I) for line in s['text'].splitlines())
                    if not receipt and not f.get('attached'):missing.append(f['label']+': file selected; upload acceptance not confirmed')
            if s.get('disabledFinal'):missing.append('Employer has disabled the final action. Check required fields and validation.')
            missing.extend(s['errors'])
            if s['final'] and any(f['label']=='E-signature' for f in s['fields']):
                missing=[m for m in missing if m!='E-signature' and not m.startswith('E-signature:')]
                concerns.append('Review your application and personally complete the e-signature before submitting.')
            if s.get('shadows'):missing.append('Shadow DOM controls require manual review')
            if s['frames']:missing.append('Embedded frame contents require manual review')
            if s.get('cards'):missing.append('Review the education or experience entries Oracle marked for correction.')
            if not s['fields'] and s.get('experience') is None and '/apply/section/' not in s['url']:missing.append('No recognizable application fields found')
            protected.update(signature(f) for f in s['fields'] if f['value'])
            self.store.update(j,protected_fields=sorted(protected))
            if not missing and s['fixture']=='multi' and s['intermediate'] and self.fixture:
                self.js(j,'next');time.sleep(.2);continue
            if s.get('experience') is not None and not missing:
                missing.append('Experience entries checked. Click Next in Safari, then resume.')
            elif not s['final']:
                missing.append('Final review stage not recognized. Navigate intermediate steps manually, then resume.')
            # Always surface location/eligibility requirements for user review without excluding any jobs.
            concerns.extend(line[:220] for line in s['text'].splitlines() if __import__('re').search(r'\b(?:must be|must have|eligible|sponsorship|relocation|on.site|work authoriz)',line,__import__('re').I))
            if any(f['type']=='checkbox' and __import__('re').search(r'agree|certify|consent|terms|attest',f['label'],__import__('re').I) and not f['value'] for f in s['fields']):concerns.append('Legal declarations must be completed by you.')
            self.store.update(j,status='Needs input' if missing or any('submission' in c.lower() for c in concerns) else 'Ready for review',filled=list(dict.fromkeys(filled)),missing=list(dict.fromkeys(missing)),concerns=list(dict.fromkeys(concerns)),last_url=s['url'],final_url=s['url'])
            return
        self.store.update(j,status='Needs input',concerns=['Step limit reached. Continue manually in Safari.'])

def make_handler(store,runner,token,fixture,port):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data,status=200,kind='application/json'):
            if not isinstance(data,bytes):data=json.dumps(data).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def trusted(self):
            return self.headers.get('Host')==f'127.0.0.1:{port}' and self.headers.get('X-JobPrep-Token')==token and self.headers.get('Origin',f'http://127.0.0.1:{port}')==f'http://127.0.0.1:{port}'
        def do_GET(self):
            path=urllib.parse.urlsplit(self.path).path
            if self.headers.get('Host')!=f'127.0.0.1:{port}':return self.send({'error':'Invalid host'},403)
            if path=='/':
                return self.send((ROOT/'dashboard.html').read_bytes(),kind='text/html; charset=utf-8')
            if path.startswith('/fixtures/') and fixture:
                from fixtures import render
                page=render(path,port)
                return self.send(page.encode(),kind='text/html; charset=utf-8')
            if not self.trusted():return self.send({'error':'Unauthorized. Open the launch URL printed in Terminal.'},403)
            if path=='/api/health':return self.send({'app':'FastApply','pid':os.getpid(),'root':str(ROOT),'healthy':ROOT.is_dir() and (ROOT/'dashboard.html').is_file() and store.path.is_dir()})
            if path=='/api/state':
                with store.lock:return self.send(store.state)
            if path=='/api/profile':return self.send({'profile':store.profile(),'path':str(store.path/'profile.json')})
            if path=='/api/sample':return self.send({'text':(ROOT/'fixtures'/'swelist.md').read_text()})
            if path=='/api/demo':return self.send({'text':'\n'.join(f'Fixture {k}: [Software Engineer](http://127.0.0.1:{port}/fixtures/listing/{k})' for k in ('normal','multi','custom','missing','expired','login','repeated','radio','guard'))})
            return self.send({'error':'Not found'},404)
        def do_POST(self):
            if fixture and self.path=='/fixtures/upload':
                if self.headers.get('Host')!=f'127.0.0.1:{port}' or self.headers.get('Origin')!=f'http://127.0.0.1:{port}':return self.send({'error':'Invalid fixture origin'},403)
                try:
                    n=int(self.headers.get('Content-Length','0'))
                    if not 0<n<=15*1024*1024:raise ValueError('Invalid file size')
                    data=self.rfile.read(n);name=self.headers.get('X-Filename','')
                    validate_resume(data,name)
                    return self.send({'accepted':True,'name':name,'bytes':len(data)})
                except ValueError:return self.send({'error':'Invalid document'},400)
            if not self.trusted():return self.send({'error':'Unauthorized request'},403)
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n>2_000_000:raise ValueError('Request too large')
                body=json.loads(self.rfile.read(n));path=urllib.parse.urlsplit(self.path).path
                if path=='/api/parse':return self.send(extract(body.get('text',''),fixture))
                if path=='/api/profile':
                    profile=body['profile']
                    validate_profile(profile)
                    atomic(store.path/'profile.json',profile);return self.send({'ok':True})
                if path=='/api/passwords':
                    import subprocess
                    if subprocess.run(['/usr/bin/open','-a','Passwords'],capture_output=True).returncode:
                        raise ValueError('Open Passwords from Spotlight to view your saved logins.')
                    return self.send({'ok':True})
                if path=='/api/resume-check':
                    f=resume(store.profile(),store.path/'cache');return self.send({'name':f['name'],'mime':f['mime'],'valid':True})
                if path=='/api/start':
                    parsed=extract(body.get('text',''),fixture)
                    with store.lock:
                        known={j['id']:j for j in store.state['jobs']};added=0;duplicates=0
                        for j in parsed['jobs']:
                            if j['id'] in known or j['id'] in store.state.get('removed_jobs',[]):duplicates+=1;continue
                            store.state['jobs'].append(j);known[j['id']]=j;added+=1
                        store.state['mode']='running';store.save()
                    return self.send({'added':added,'previously_prepared':duplicates,'warnings':parsed['warnings']})
                if path=='/api/control':
                    mode=body.get('mode')
                    if mode not in ('running','paused','cancelled'):raise ValueError('Invalid mode')
                    with store.lock:
                        store.state['mode']=mode
                        if mode=='cancelled':
                            for j in store.state['jobs']:
                                if j['status']=='Queued':j.update(status='Needs input',concerns=['Cancelled before opening. Resume this job explicitly.'])
                        store.save()
                    return self.send({'ok':True})
                if path=='/api/job':
                    with store.lock:
                        j=next(j for j in store.state['jobs'] if j['id']==body['id']);action=body['action']
                        if action=='remove':
                            store.state['jobs'].remove(j)
                            store.state.setdefault('removed_jobs',[])
                            if j['id'] not in store.state['removed_jobs']:store.state['removed_jobs'].append(j['id'])
                            store.save()
                            return self.send({'ok':True})
                        if j['status'] in ('Opening','Filling'):raise ValueError('Pause and wait for the current operation before editing this job.')
                        if action=='focus':
                            if not j.get('window'):raise ValueError('No Safari window opened yet')
                            runner.browser.focus(j['window'])
                        elif action in ('resume','reopen'):
                            if action=='reopen':j['window']=None;j['opening_pending']=False;j['protected_fields']=[]
                            if j.get('opening_pending'):raise ValueError('Interrupted during window creation. Inspect Safari first, then explicitly Reopen if needed.')
                            j['manual']=None
                            j['country']=body.get('country') or j.get('country');j['status']='Queued';j['missing']=[];j['concerns']=[];store.state['mode']='running'
                        elif action in ('scan','learn'):
                            if not j.get('window'):raise ValueError('Open the employer application first.')
                            snap=runner.js(j,'inspect')
                            if not snap or not j.get('final_url') or urllib.parse.urlsplit(snap['url']).netloc!=urllib.parse.urlsplit(j['final_url']).netloc:
                                raise ValueError('Open the tracked employer application before scanning.')
                            candidates=scan_answers(snap['fields'])
                            if action=='scan':return self.send({'answers':candidates})
                            shown=body.get('answers',{})
                            if any(key not in candidates or entry!=candidates[key] for key,entry in shown.items()):
                                raise ValueError('The form changed. Scan it again before saving.')
                            learned=store.state.setdefault('learned_answers',{})
                            share=body.get('share',[])
                            if not isinstance(share,list) or any(key not in shown for key in share):
                                raise ValueError('Select an answer before sharing it across employers.')
                            for key,entry in shown.items():
                                scope=reusable_scope(key,entry,share,j)
                                learned.setdefault(scope,{})[key]={'value':entry['value']}
                                if scope=='shared':
                                    learned.get(answer_scope(j),{}).pop(key,None)
                            store.save()
                            return self.send({'saved':len(shown)})
                        elif action=='account':
                            host=urllib.parse.urlsplit(j.get('final_url') or '').hostname
                            if not host:raise ValueError('Open the employer site first.')
                            accounts=store.state.setdefault('accounts',{})
                            accounts[host]={'company':j['company'],'site':'https://'+host,'email':store.profile().get('email') or ''}
                        elif action in ('submitted','skipped'):j['manual']=action
                        else:raise ValueError('Unknown action')
                        store.save()
                    return self.send({'ok':True})
                return self.send({'error':'Not found'},404)
            except (ValueError,KeyError,TypeError,AttributeError,StopIteration,SafariError,OSError) as e:
                return self.send({'error':str(e) if isinstance(e,(ValueError,SafariError)) else 'Invalid input or unreadable local file'},400)
    return Handler

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8874);parser.add_argument('--data-dir',type=pathlib.Path,default=ROOT/'private');parser.add_argument('--fixtures',action='store_true');parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
    os.umask(0o077);args.data_dir.mkdir(parents=True,exist_ok=True)
    lockfile=open(args.data_dir/'instance.lock','a')
    for attempt in range(2):
        try:
            fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
            break
        except BlockingIOError:
            try:
                launch=json.loads((args.data_dir/'launch.json').read_text());url=launch['url']
                parsed=urllib.parse.urlsplit(url)
                if parsed.hostname!='127.0.0.1' or parsed.scheme!='http':raise ValueError('Invalid local launch URL')
                saved_token=urllib.parse.parse_qs(parsed.fragment)['token'][0]
                req=urllib.request.Request(urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'/api/health','','')),headers={'X-JobPrep-Token':saved_token})
                with urllib.request.urlopen(req,timeout=3) as response:health=json.load(response)
                if health.get('app')!='FastApply':raise ValueError('Unrecognized server')
                if health.get('healthy') and health.get('root')==str(ROOT):
                    print('FastApply is already running. Open: '+url,flush=True)
                    if not args.no_open:Safari().open(url)
                    return
                if attempt:raise ValueError('Previous instance did not stop')
                print('Project location changed. Restarting FastApply from this folder.',flush=True)
                os.kill(int(health['pid']),signal.SIGTERM)
                for _ in range(50):
                    time.sleep(.1)
                    try:
                        fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        break
                    except BlockingIOError:continue
                else:raise ValueError('Previous instance did not stop')
                break
            except (OSError,ValueError,KeyError,SafariError):
                print('An existing FastApply instance is not responding correctly. Close its Terminal process, then launch again. Your profile is saved.',flush=True)
                return
    store=Store(args.data_dir);token=secrets.token_urlsafe(32);runner=Runner(store,args.fixtures)
    try:server=http.server.ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(store,runner,token,args.fixtures,args.port))
    except OSError:
        print(f'Port {args.port} is unavailable. Launch with --port 8875 (or another unused port).');return
    url=f'http://127.0.0.1:{args.port}/#token={token}'
    atomic(args.data_dir/'launch.json',{'url':url})
    def stop(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    print('FastApply is local-only. Review and submit every application yourself.\nOpen: '+url,flush=True)
    if not args.no_open:
        try:runner.browser.open(url)
        except SafariError:print('Open the launch URL above in Safari. Automation permission may be needed.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        store.state['mode']='paused'
        try:store.save()
        except OSError:pass  # The project may have moved; recover from its last atomic save.
        server.server_close()
if __name__=='__main__':main()
