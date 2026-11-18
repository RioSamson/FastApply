import unittest, pathlib, tempfile, json
from core import extract, canonical, plan, safe_url, validate_resume, simplify_target, embedded_application, validate_profile
from app import Store

class Tests(unittest.TestCase):
    def test_sample_email(self):
        text=pathlib.Path('fixtures/swelist.md').read_text();jobs=extract(text)['jobs']
        expected=[(f'Example Company {i}', f'Example role {i}', f'fixture-job-{i}') for i in range(1,10)]
        self.assertEqual(len(jobs),9)
        for j,(company,title,uid) in zip(jobs,expected):self.assertEqual((j['company'],j['title'],j['original_url']),(company,title,'https://simplify.jobs/p/'+uid+'?utm_source=swelist'))
        self.assertEqual(len(extract(text+'\n'+text)['jobs']),9)
        self.assertTrue(all('simplify.jobs/p/' in j['original_url'] for j in jobs))
    def test_tracking(self):
        self.assertEqual(canonical('https://simplify.jobs/p/abc?utm_source=x&jobId=42'),canonical('https://simplify.jobs/p/abc?jobId=42&utm_source=y'))
        self.assertNotEqual(canonical('https://x.com/job?id=1'),canonical('https://x.com/job?id=2'))
    def test_plain_and_table(self):
        self.assertEqual(extract('Acme\nEngineer\nhttps://simplify.jobs/p/abc')['jobs'][0]['title'],'Engineer')
        self.assertEqual(extract('| Acme | Engineer | [Apply](https://simplify.jobs/p/abc) |')['jobs'][0]['company'],'Acme')
    def test_legal_and_unknown(self):
        fs=[{'id':str(i),'label':l,'value':'','type':'text','required':True} for i,l in enumerate(['Email','I agree to terms','Are you authorized to work in Canada','Desired salary'])]
        p=plan(fs,{'email':'synthetic@example.invalid','address':{'country':'Canada'},'answers':{'i agree to terms':{'value':True},'are you authorized to work in canada':{'value':'Yes','country':'CA'}}})
        self.assertEqual(len(p['answers']),1)
        p=plan(fs,{'answers':{'are you authorized to work in canada':{'value':'Yes','country':'CA'}}},'CA');self.assertEqual(len(p['answers']),1)
    def test_preserve_edits(self):
        self.assertFalse(plan([{'id':'a','label':'Email','type':'email','value':'manual@example.invalid','required':True}],{'email':'other@example.invalid'})['answers'])
    def test_urls(self):
        for url in ['https://email.example/unsubscribe/a','file:///etc/passwd','http://localhost/a','https://127.0.0.1/a','javascript:alert(1)']:self.assertFalse(safe_url(url))
    def test_invalid_resume(self):
        for data,name in [(b'<html>login</html>','resume.pdf'),(b'PKbad','resume.docx')]:
            with self.assertRaises(ValueError):validate_resume(data,name)
    def test_navigation_adapters(self):
        s={'url':'https://simplify.jobs/p/abc/title','simplify':{'id':'abc','url':'https://simplify.jobs/jobs/click/abc'}}
        self.assertEqual(simplify_target(s,'https://simplify.jobs/p/abc'),s['simplify']['url'])
        self.assertIsNone(simplify_target(s,'https://simplify.jobs/p/other'))
        u='https://job-boards.greenhouse.io/embed/job_app?for=company&token=123'
        self.assertEqual(embedded_application({'frame_urls':[u]}),u)
        self.assertIsNone(embedded_application({'frame_urls':['https://evil.example/embed/job_app?for=x&token=1']}))
    def test_authorization_not_inverted(self):
        f={'id':'1','label':'Can you work without sponsorship','value':'','type':'text','required':True}
        p={'work_authorization':{'CA':{'sponsorship_required':True}}}
        self.assertFalse(plan([f],p,'CA')['answers'])
    def test_repeated_dates(self):
        f={'id':'1','label':'Start date','value':'','type':'date','required':True,'section':'Education','sectionIndex':1}
        self.assertEqual(plan([f],{'education':[{}, {'start_date':'2024-09-01'}]})['answers'][0]['value'],'2024-09-01')
    def test_profile_structure(self):
        with self.assertRaisesRegex(ValueError,'education must be a list of objects'):
            validate_profile({'education':['Example University']})
        with self.assertRaisesRegex(ValueError,'work_authorization must be an object'):
            validate_profile({'work_authorization':['Not for US']})
        validate_profile({'education':[{'school':'Example University'}],'employment':[{'company':'Example employer'}],'skills':['Python']})
    def test_scan_age_radio_reuses_yes_no(self):
        from app import scan_answers
        from core import plan
        group = {'type':'radio','question':'Are you at least 18 years of age?','required':True}
        selected = dict(group,id='1',label='Yes',option='1',value='1',groupAnswered=True)
        rejected = dict(group,id='2',label='No',option='2',value='',groupAnswered=True)
        saved = scan_answers([selected,rejected,dict(selected,question='Enter verification code')])
        self.assertEqual(list(saved),['are you at least 18 years old'])
        for field in (selected,rejected):
            field.update(question='Are you 18 or older?',value='',groupAnswered=False)
        self.assertEqual(plan([selected,rejected],{'answers':saved})['answers'],[{'id':'1','checked':True}])

    def test_location_preference_uses_best_available_option(self):
        from core import plan
        choices=[{'label':name,'value':name,'disabled':False} for name in ('Austin, TX','Los Angeles, CA','Seattle, WA')]
        field={'id':'1','label':'Preferred location','value':'','type':'select-one','required':True,'options':choices}
        profile={'availability':{'location_preferences':['Vancouver','Seattle','Anywhere in California','New York','Texas']}}
        self.assertEqual(plan([field],profile)['answers'],[{'id':'1','value':'Seattle, WA'}])

    def test_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);s=Store(p);s.state['jobs']=[{'id':'1','status':'Filling','window':123,'concerns':[]}];s.save();r=Store(p)
            self.assertEqual(r.state['mode'],'paused');self.assertEqual(r.state['jobs'][0]['window'],123);self.assertEqual(r.state['jobs'][0]['status'],'Needs input')
if __name__=='__main__':unittest.main()
