import re, json, hashlib, urllib.parse, urllib.request, ipaddress, socket, pathlib, zipfile, io, base64

TRACKING={'ref','referrer','source','gh_src','fbclid','gclid','mc_cid','mc_eid'}
def canonical(url):
    p=urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urllib.parse.urlencode(sorted((k,v) for k,v in urllib.parse.parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in TRACKING)),''))

def safe_url(url, fixture=False):
    p=urllib.parse.urlsplit(url)
    if p.username or p.password or p.scheme not in ('http','https') or not p.hostname: return False
    if re.search(r'unsubscribe|signout|logout|delete|submitapplication',p.path,re.I): return False
    if p.hostname=='127.0.0.1': return fixture and p.path.startswith('/fixtures/')
    if p.scheme!='https' or p.hostname in ('localhost',) or '.' not in p.hostname: return False
    try:
        if not ipaddress.ip_address(p.hostname).is_global:return False
    except ValueError: pass
    return True

def listing(url, fixture=False):
    if not safe_url(url,fixture):return False
    p=urllib.parse.urlsplit(url)
    return (p.hostname in ('simplify.jobs','www.simplify.jobs') and bool(re.match(r'^/(?:p|jobs)/[^/]+',p.path))) or (fixture and p.hostname=='127.0.0.1')

def extract(text,fixture=False):
    jobs=[]; seen=set(); warnings=[]
    lines=text.splitlines()
    for i,line in enumerate(lines):
        links=re.findall(r'\[([^\]]*)\]\((https?://[^\s)]+)\)',line)
        urls=re.findall(r'https?://[^\s<>\])]+',line)
        for url in dict.fromkeys(urls):
            url=url.rstrip('.,;')
            if not listing(url,fixture):continue
            key=canonical(url)
            if key in seen:continue
            seen.add(key)
            clean=lambda s:re.sub(r'[*#`>]+','',re.sub(r'\[([^\]]*)\]\([^)]*\)',r'\1',s)).strip(' |:-')
            title=company=''
            if '|' in line:
                cells=[clean(x) for x in line.strip('|').split('|')]
                if len(cells)>=2:company,title=cells[:2]
            if not title and re.match(r'^\s*[^:]+:\s*\[',line):
                company=clean(line.split(':',1)[0]);title=next((a for a,b in links if b==url),'')
            if not title and ':' in re.sub(r'https?://\S+','',line):
                parts=re.sub(r'https?://\S+','',line).split(':',1);company,title=map(clean,parts)
            if not title:
                label=next((a for a,b in links if b==url and a.lower() not in ('apply','simplify','apply here','link','view job')),'')
                context=[clean(x) for x in lines[max(0,i-3):i] if x.strip()]
                desc=label or clean(re.sub(r'https?://\S+','',line))
                m=re.match(r'(.+?)\s+(?:at|@)\s+(.+)',desc,re.I)
                if m:title,company=m.groups()
                elif ' — ' in desc or ' - ' in desc:
                    company,title=re.split(r' — | - ',desc,maxsplit=1)
                elif len(context)>=2:company,title=context[-2:]
                else:title=desc or 'Title needs review';company=context[-1] if context else 'Company needs review'
            jobs.append({'id':hashlib.sha256(key.encode()).hexdigest()[:20], 'company':company,'title':title,'original_url':url,'canonical_url':key,'status':'Queued','filled':[],'missing':[],'concerns':[], 'window':None,'final_url':None,'manual':None})
    if not jobs:warnings.append('No recognizable Simplify listing URLs found. Use direct simplify.jobs/p/… links. Tracking-wrapper-only emails need review.')
    if any('needs review' in j['company']+j['title'] for j in jobs):warnings.append('Some company/title metadata needs review; all recognized listings are retained.')
    return {'jobs':jobs,'warnings':warnings}

ALIASES={
'first name':'first_name','given name':'first_name','middle name':'middle_name','middle initial':'middle_initial','country of residence':'address.country','last name':'last_name','family name':'last_name','full name':'name','name':'name','email':'email','email address':'email','phone':'phone','phone number':'phone','mobile phone':'phone','linkedin':'linkedin','linkedin profile':'linkedin','linkedin url':'linkedin','github':'github','github url':'github','portfolio':'portfolio','website':'portfolio','address':'address.street','street address':'address.street','address line 1':'address.street','city':'address.city','state':'address.region','province':'address.region','postal code':'address.postal_code','zip code':'address.postal_code','country':'address.country','skills':'skills'}
SENSITIVE=re.compile(r'authori[sz]|sponsor|citizen|visa|salary|compensation|available|availability|start date|notice period|relocat|student|veteran|disabil|gender|ethnic|race|pronoun|\bage\b|birth|sexual|nationality',re.I)
LEGAL=re.compile(r'agree|accept|acknowledge|confirm|certify|consent|signature|declaration|terms|attest|privacy|policy',re.I)
def norm(s):return re.sub(r'[^\w ]','',s.lower()).strip()
def answer_key(label):
    cleaned=norm(label)
    if re.fullmatch(r'are you (?:(?:at least|at years|over) )?18(?: years (?:of age|old))?(?: or older)?',cleaned) and 'over' not in cleaned:
        return 'are you at least 18 years old'
    return cleaned

def demographic(label):
    return bool(re.search(r'gender|ethnic|race|hispanic|latino|veteran|military|disabil|sexual|pronoun',label,re.I))

def learnable(label):
    if answer_key(label) in {'select', 'search', 'textbox', 'combobox', 'choose'}:
        return False
    if LEGAL.search(label) or re.search(r'password|verification|one time|security code|social security|\bssn\b|passport|bank|tax id|pin code|secret|credential|birth|religion',label,re.I):
        return False
    return demographic(label) or not SENSITIVE.search(label) or answer_key(label)=='are you at least 18 years old'

def preferred_location(location, preferences):
    text=str(location).casefold()
    patterns={'anywhere in california':r'california|\bca,? (?:us|usa)\b|, ca(?:$|,)',
              'new york':r'new york|\bnyc\b|, ny\b','texas':r'texas|, tx\b',
              'vancouver':r'\bvancouver\b(?!,?\s*(?:wa|washington)\b)'}
    for rank,preference in enumerate(preferences,1):
        if re.search(patterns.get(preference.casefold(),r'\b'+re.escape(preference.casefold())+r'\b'),text):
            return rank,preference
    return None

def getpath(d,key):
    for k in key.split('.'):
        if not isinstance(d,dict):return None
        d=d.get(k)
    return d

def plan(fields,profile,country=None):
    answers=[];missing=[]
    for f in fields:
        label=f['label']; n=answer_key(label); value=None
        question=f.get('question') or label
        if f.get('groupAnswered'):continue
        if f['value']:continue
        if LEGAL.search(label) or LEGAL.search(question):missing.append(label+': review and act yourself');continue
        # An individually approved response takes precedence over the general blank preference.
        answer=profile.get('answers',{}).get(answer_key(question))
        if demographic(question):
            if not isinstance(answer,dict) or answer.get('demographic_approved') is not True:
                continue
            value=answer.get('value')
        elif isinstance(answer,dict) and answer.get('value') is not None:
            if answer_key(question)=='are you at least 18 years old' or not SENSITIVE.search(question) or (country and answer.get('country')==country):value=answer['value']
        if value is None and country:
            wa=profile.get('work_authorization',{}).get(country,{})
            key=None
            if re.fullmatch(r'are you (?:legally )?authori[sz]ed to work(?: in [\w ]+)?',n):key='authorized'
            if re.fullmatch(r'(?:do|will) you (?:now or in the future )?require (?:visa |employment )?sponsorship(?: for employment)?',n):key='sponsorship_required'
            if isinstance(wa,dict) and key and isinstance(wa.get(key),bool):value='Yes' if wa[key] else 'No'
        section=norm(f.get('section',''))
        group='education' if 'education' in section else 'employment' if 'employment' in section or 'experience' in section else None
        if group and n in ('start date','end date'):
            rows=profile.get(group,[]);index=max(0,f.get('sectionIndex',0))
            if index<len(rows):value=rows[index].get(n.replace(' ','_'))
        if value is None and not SENSITIVE.search(label):
            value=getpath(profile,ALIASES.get(n,''))
            section=norm(f.get('section',''))
            group='education' if 'education' in section else 'employment' if 'employment' in section or 'experience' in section else None
            if group:
                rows=profile.get(group,[]); index=max(0,f.get('sectionIndex',0))
                keys={'school':'school','university':'school','degree':'degree','field of study':'field','company':'company','job title':'title','start date':'start_date','end date':'end_date','description':'description'}
                if index<len(rows) and n in keys:value=rows[index].get(keys[n])
        if value is None and n in ('preferred location','preferred work location') and f.get('options'):
            ranked=[(match[0],option['value']) for option in f['options'] if not option['disabled'] and option['value']
                    if (match:=preferred_location(option['label'],profile.get('availability',{}).get('location_preferences',[])))]
            if ranked:
                best=min(rank for rank,_ in ranked)
                values={option for rank,option in ranked if rank==best}
                if len(values)==1:value=values.pop()
        if isinstance(value,list):value=', '.join(map(str,value))
        if value is not None and value!='':
            if f['type'] in ('radio','checkbox'):
                if f['type']=='checkbox' and value is True:answers.append({'id':f['id'],'checked':True})
                elif str(value).lower()==str(f.get('option','')).lower() or (f['type']=='radio' and norm(str(value))==norm(label)):answers.append({'id':f['id'],'checked':True})
                continue
            if f.get('options'):
                options=[o for o in f['options'] if not o['disabled'] and (norm(str(value))==norm(o['label']) or str(value)==o['value'])]
                if len(options)!=1:missing.append(label+': no unique matching option');continue
                value=options[0]['value']
            if f['type']=='combobox':
                choice={'id':f['id'],'value':value,'custom':True}
                address=profile.get('address',{})
                if n in ('city','postal code') and address.get('city') and address.get('region'):
                    locality=address['city']+', '+address['region']
                    choice['aliases']=[locality if n=='city' else str(value)+', '+locality]
                answers.append(choice)
                continue
            answers.append({'id':f['id'],'value':value})
        elif f['required'] and f['type']!='file':missing.append(label+': no applicable saved answer')
    return {'answers':answers,'missing':missing}

def validate_resume(data,name):
    suffix=pathlib.Path(name).suffix.lower()
    if not data or len(data)>15*1024*1024:raise ValueError('Resume must be nonempty and under 15 MB.')
    if suffix=='.pdf' and data.startswith(b'%PDF-') and b'%%EOF' in data[-2048:]:return 'application/pdf'
    if suffix=='.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if 'word/document.xml' in z.namelist():return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        except zipfile.BadZipFile:pass
    raise ValueError('Resume must be an actual PDF or DOCX, not an HTML login page or a sharing link.')

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check_download(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def check_download(url):
    if not safe_url(url):raise ValueError('Use a public HTTPS document URL.')
    host=urllib.parse.urlsplit(url).hostname
    if any(not ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(host,443)):raise ValueError('Resume URL must resolve to a public address.')
def resume(profile,cache):
    path=profile.get('resume_path')
    if path:
        p=pathlib.Path(path).expanduser();data=p.read_bytes();name=p.name
    elif profile.get('resume_url'):
        url=profile['resume_url'];check_download(url)
        with urllib.request.build_opener(SafeRedirect()).open(url,timeout=15) as r:
            data=r.read(15*1024*1024+1);name=pathlib.Path(urllib.parse.urlsplit(r.url).path).name
        # Content magic permits a download endpoint with no useful extension.
        if data.startswith(b'%PDF-'):name='resume.pdf'
        elif data.startswith(b'PK'):name='resume.docx'
        mime=validate_resume(data,name)
        p=cache/('resume-'+hashlib.sha256(data).hexdigest()[:12]+pathlib.Path(name).suffix);p.write_bytes(data);p.chmod(0o600)
    else:raise ValueError('Set a local resume_path or a directly downloadable resume_url.')
    mime=validate_resume(data,name)
    return {'name':name,'mime':mime,'base64':base64.b64encode(data).decode()}


def simplify_target(snapshot, original):
    if urllib.parse.urlsplit(snapshot.get('url','')).hostname not in ('simplify.jobs','www.simplify.jobs'):return None
    data=snapshot.get('simplify') or {};uid=data.get('id')
    if not uid or uid not in urllib.parse.urlsplit(original).path.split('/'):return None
    target=data.get('url','');p=urllib.parse.urlsplit(target)
    if p.hostname in ('simplify.jobs','www.simplify.jobs') and p.path=='/jobs/click/'+uid and safe_url(target):return target
    return None


def embedded_application(snapshot):
    candidates=[]
    for url in snapshot.get('frame_urls',[]):
        p=urllib.parse.urlsplit(url)
        if p.hostname in ('job-boards.greenhouse.io','boards.greenhouse.io') and p.path=='/embed/job_app' and safe_url(url):
            q=urllib.parse.parse_qs(p.query)
            if q.get('for') and q.get('token'):candidates.append(url)
    return candidates[0] if len(candidates)==1 else None


def validate_profile(profile):
    if not isinstance(profile,dict):raise ValueError('Profile must be a JSON object')
    for key in ('education','employment'):
        rows=profile.get(key,[])
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
            example='{"school": "Your university"}' if key=='education' else '{"company": "Your employer"}'
            raise ValueError(key+' must be a list of objects, for example ['+example+']')
    if not isinstance(profile.get('skills',[]),list) or any(not isinstance(x,str) for x in profile.get('skills',[])):raise ValueError('skills must be a list of quoted strings')
    for key in ('address','availability','work_authorization','demographics','answers'):
        if not isinstance(profile.get(key,{}),dict):raise ValueError(key+' must be an object with named values')
    for country,answer in profile.get('work_authorization',{}).items():
        if not isinstance(answer,dict):raise ValueError('Each work_authorization country must contain an object')
    for answer in profile.get('answers',{}).values():
        if not isinstance(answer,dict):raise ValueError('Each reusable answer must be an object containing value')
    return profile
