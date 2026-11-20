"""Ordinary Safari tabs via Apple Events. Never uses WebDriver or closes windows."""
import json, subprocess

class SafariError(RuntimeError): pass

class Safari:
    def script(self, source):
        try:
            p = subprocess.run(['/usr/bin/osascript', '-'], input='with timeout of 20 seconds\n'+source+'\nend timeout', text=True, capture_output=True, timeout=24)
        except subprocess.TimeoutExpired:
            raise SafariError('Safari timed out. Check macOS Automation permission and Safari dialogs.')
        if p.returncode:
            # Do not include the script, page contents, or profile in errors.
            if 'JavaScript from Apple Events' in p.stderr:
                raise SafariError('Enable Safari Settings → Developer → Allow JavaScript from Apple Events.')
            raise SafariError('Safari automation unavailable. Check Automation permissions, open windows, and dialogs.')
        return p.stdout.strip()

    def open(self, url):
        # A dedicated window isolates tab identity from unrelated browsing.
        return int(self.script('tell application "Safari"\nmake new document with properties {URL:'+json.dumps(url)+'}\nreturn id of front window\nend tell'))

    def ensure(self, window):
        count = int(self.script('tell application "Safari" to count tabs of window id '+str(int(window))))
        if count != 1: raise SafariError("This job window now has multiple tabs. Move the additional tabs to another window before resuming.")

    def evaluate(self, window, js):
        self.ensure(window)
        raw = self.script('tell application "Safari"\nreturn do JavaScript '+json.dumps(js)+' in tab 1 of window id '+str(int(window))+'\nend tell')
        return json.loads(raw) if raw else None

    def location(self, window):
        self.ensure(window)
        return self.script('tell application "Safari" to return URL of tab 1 of window id '+str(int(window)))

    def navigate(self, window, url):
        self.ensure(window)
        self.script('tell application "Safari" to set URL of tab 1 of window id '+str(int(window))+' to '+json.dumps(url))

    def focus(self, window):
        self.script('tell application "Safari"\nset index of window id '+str(int(window))+' to 1\nactivate\nend tell')

    def tabs(self, window):
        # Use explicit positions only within a single Apple Event. Safari exposes no persistent tab ID.
        script = f'''tell application "Safari"
set output to ""
repeat with t in tabs of window id {int(window)}
    set u to URL of t
    if u is missing value then set u to ""
    set output to output & u & linefeed
end repeat
return output
end tell'''
        return self.script(script).split('\n')

    def open_job(self, url, window=None):
        if window is not None:
            try:
                self.script(f'tell application "Safari" to count tabs of window id {int(window)}')
            except SafariError:
                window=None
        if window is None:
            return self.open(url)
        self.script(f'''tell application "Safari"
tell window id {int(window)} to make new tab at end of tabs with properties {{URL:{json.dumps(url)}}}
end tell''')
        return window

    def in_tab(self, window, index, expected_url, command):
        script=f'''tell application "Safari"
set tracked to tab {int(index)} of window id {int(window)}
if URL of tracked is not {json.dumps(expected_url)} then error "Job tab moved"
{command}
end tell'''
        return self.script(script)
