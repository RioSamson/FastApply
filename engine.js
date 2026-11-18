/* Runs in an ordinary Safari tab. No submission API and no generic button clicks. */
(() => {
  const op = __OP__, payload = __PAYLOAD__;
  const visible = e => !!(e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
  const norm = s => (s || '').replace(/\s+/g,' ').trim();
  function ripplingFile(e) {
    if(location.hostname!=='ats.rippling.com'||e.type!=='file')return '';
    const wrapper=e.parentElement?.parentElement?.parentElement;
    const title=norm(wrapper?.innerText.split('\n')[0]);
    return /^r\u00e9sum\u00e9\*?$/i.test(title)?'Resume':title==='Cover letter'?'Cover letter':'';
  }
  const label = e => e.closest('.apply-flow-esign,.esign-form') ? 'E-signature' : e.matches('button[role=radio]') ? norm(e.innerText) : ripplingFile(e) || (e.type==='file' && e.id==='resume') ? (ripplingFile(e)||'Resume') : norm(e.getAttribute('aria-label') || [...(e.labels || [])].map(x=>x.innerText).filter(Boolean).join(' ') || document.getElementById(e.getAttribute('aria-labelledby'))?.innerText || e.getAttribute('placeholder') || e.name || e.id);

  const elements = () => { document.querySelectorAll('[data-jobprep-id]').forEach(e=>e.removeAttribute('data-jobprep-id')); return [...document.querySelectorAll('input,select,textarea,[role="combobox"],button[type=button][role=radio]')].filter(e => (visible(e)||ripplingFile(e)) && !e.closest('.ashby-application-form-autofill-pane,.ashby-application-form-autofill-uploader') && !e.disabled && (e.matches('button[role=radio]') || !['hidden','submit','button','reset'].includes(e.type))); };
  const field = (e,i) => {
    e.dataset.jobprepId = String(i);
    const section = e.closest('fieldset');
    const siblings = section ? [...document.querySelectorAll('fieldset')].filter(s => norm(s.querySelector('legend')?.innerText) === norm(section.querySelector('legend')?.innerText)) : [];
    const wrapper=e.closest('.ashby-application-form-field-entry');
    const heading=wrapper?.querySelector('label');
    const ripplingReceipt=ripplingFile(e)==='Resume' && e.parentElement.parentElement.parentElement.innerText.match(/File ([^\n]+) uploaded successfully/i);
    const attached=e.type==='file' && e.files.length && wrapper?.innerText.includes(e.files[0].name) && /\bReplace\b/.test(wrapper.innerText);
    const selection=e.closest('.select__value-container')?.querySelector('.select__single-value')?.innerText;
    const pill=e.matches('button[role=radio]');
    const radioGroup=(pill || e.type==='radio') && (e.closest('[role=radiogroup]')||section||wrapper);
    const question=radioGroup ? norm(document.getElementById(radioGroup.getAttribute('aria-labelledby'))?.innerText || radioGroup.getAttribute('aria-label') || radioGroup.querySelector('legend')?.innerText || heading?.innerText) : '';
    const siblingsInGroup=e.type==='radio' && e.name ? [...(e.form||document).querySelectorAll('input[type=radio]')].filter(r=>r.name===e.name && r.form===e.form) : [];
    return {question,groupAnswered:pill ? !!radioGroup?.querySelector('[aria-checked=true]') : siblingsInGroup.some(r=>r.checked),selectedLabel:e.selectedOptions?.[0]?.text || selection || e.getAttribute('aria-valuetext') || '',attached:!!ripplingReceipt || !!attached || (ripplingFile(e)==='Resume' && !!e.files.length && /Total 1 file selected/i.test(e.parentElement.parentElement.innerText) && e.parentElement.parentElement.innerText.includes(e.files[0].name)),manual:e.dataset.fastapplyManual==='yes',ashbyQuestion:!!wrapper && e.tagName==='TEXTAREA',id:String(i),label:label(e),type:pill ? 'radio' : e.getAttribute('role')==='combobox' ? 'combobox' : e.type || e.getAttribute('role'),tag:e.tagName,required:ripplingFile(e)==='Resume' || e.required || e.getAttribute('aria-required')==='true', value:pill ? (e.getAttribute('aria-checked')==='true' ? label(e) : '') : e.type==='file' ? (ripplingReceipt?.[1] || [...e.files].map(f=>f.name).join(', ')) : e.type==='radio'||e.type==='checkbox' ? (e.checked ? e.value : '') : e.closest('.select__value-container') ? selection || '' : e.value || e.getAttribute('aria-valuetext') || '',
      option:pill ? label(e) : e.value, section:norm(section?.querySelector('legend')?.innerText), sectionIndex:siblings.indexOf(section),
      options:e.options ? [...e.options].map(o=>({value:o.value,label:o.text,disabled:o.disabled})) : [], invalid:e.validity ? !e.validity.valid : e.getAttribute('aria-invalid')==='true', validation:e.validationMessage || ''};
  };
  const simplify = () => {
    if(!['simplify.jobs','www.simplify.jobs'].includes(location.hostname)) return null;
    try { const j=JSON.parse(document.getElementById('__NEXT_DATA__').textContent).props.pageProps.jobPosting;
      return {id:j.id,url:j.url,active:j.active,locations:(j.locations||[]).map(l=>l.value),requirements:j.requirements||[]};
    } catch {return null;}
  };
  function entryButton() {
    const host=location.hostname, path=location.pathname;
    let selector;
    if(host.endsWith('.oraclecloud.com') && /^\/hcmUI\/CandidateExperience\/[^/]+\/sites\/[^/]+\/job\/\d+\/?$/.test(path))
      selector='button.apply-now-button--apply-now';
    else if(host.endsWith('.careers.hibob.com') && /^\/jobs\/[\w-]+\/?$/.test(path))
      selector='span,button.primary';
    else if(host==='ats.rippling.com' && /^\/(?:[\w-]+\/)?[\w-]+\/jobs\/[\w-]+\/?$/.test(path))
      selector='button';
    else return null;
    if(document.querySelector('input[type=file],input[type=email],input[type=password]') || [...document.forms].some(visible))return null;
    return [...document.querySelectorAll(selector)].find(e=>visible(e)&&!e.disabled&&!e.form&&(/^apply( now)?$/i.test(norm(e.innerText)) || (host.endsWith('.careers.hibob.com') && norm(e.innerText)==='Application')));
  }
  function locationInput(){
    if(location.hostname!=='ats.rippling.com')return null;
    return [...document.querySelectorAll('input[aria-autocomplete=list]')].find(e=>visible(e) && /^location\s*\*?$/i.test(norm(document.getElementById(e.getAttribute('aria-labelledby'))?.innerText)));
  }
  function oracleCards(){
    if(location.hostname!=='jpmc.fa.oraclecloud.com' || !location.pathname.includes('/apply/section/'))return [];
    return [...document.querySelectorAll('article.apply-flow-profile-item-tile--invalid')].filter(visible).map(tile=>({
      id:tile.id,title:norm(tile.querySelector('.apply-flow-profile-item-tile__summary-title')?.innerText),
      subtitle:norm(tile.querySelector('.apply-flow-profile-item-tile__summary-subtitle')?.innerText)
    }));
  }
  const snapshot = () => ({cards:oracleCards(),locationNeeded:!!locationInput() && (!locationInput().value || locationInput().getAttribute('aria-invalid')==='true' || document.getElementById(locationInput().id+'-list')?.getClientRects().length),entry:!!entryButton(),simplify:simplify(),url:location.href,title:document.title,ready:document.readyState,text:document.body.innerText.slice(0,35000),fields:elements().map(field),
    links:[...document.querySelectorAll('a[href]')].filter(visible).map(a=>({text:norm(a.innerText||a.getAttribute('aria-label')),url:a.href})),
    shadows:[...document.querySelectorAll('*')].filter(e=>e.shadowRoot).length,frame_urls:[...document.querySelectorAll('iframe[src]')].map(e=>e.src),frames:[...document.querySelectorAll('iframe')].filter(e=>visible(e) && e.clientHeight>2 && e.clientWidth>2 && !/recaptcha.*\/anchor/.test(e.src)).length,custom:document.querySelectorAll('[role="combobox"]').length,
    errors:[...document.querySelectorAll('[role="alert"],.error,.field-error,[aria-invalid="true"]')].filter(e=>visible(e) && e.id!=='__next-route-announcer__' && !(location.hostname.endsWith('.oraclecloud.com') && e.matches('[role=alert].oj-helper-hidden-accessible'))).map(e=>norm(e.innerText || (e.matches('[aria-invalid=true]')?label(e):''))).filter(msg=>msg && !(location.hostname.endsWith('.oraclecloud.com') && msg==='Saved')).slice(0,20),
    fixture:document.documentElement.dataset.jobprepFixture || '',
    intermediate:!!document.querySelector('button[data-jobprep-next]'),
    disabledFinal:[...document.querySelectorAll('button[type=submit]')].some(e=>visible(e)&&(e.disabled||e.getAttribute('aria-disabled')==='true')),final:[...document.querySelectorAll('button,input[type="submit"]')].filter(visible).some(e=>/submit|send application|apply/i.test(e.innerText||e.value))});
  if(!window.__fastapplyObserve){
    document.addEventListener('change',e=>{if(e.isTrusted && e.target.matches('input[type=text],input[type=email],input[type=tel],input[type=url],textarea'))e.target.dataset.fastapplyManual='yes';},true);
    window.__fastapplyObserve=true;
  }
  if(op==='inspect') return JSON.stringify(snapshot());
  const filled=[], issues=[];
  // Safety guard applies only during this synchronous filling operation; user submission stays available afterward.
  const stop=e=>{ e.preventDefault(); e.stopImmediatePropagation(); issues.push('A page attempted form submission while filling; blocked.'); };
  const oldSubmit=HTMLFormElement.prototype.submit,oldRequest=HTMLFormElement.prototype.requestSubmit;
  document.addEventListener('submit',stop,true);
  HTMLFormElement.prototype.submit=function(){issues.push('Blocked scripted form submission.');};
  HTMLFormElement.prototype.requestSubmit=function(){issues.push('Blocked scripted form submission.');};
  try {
    if(op==='edit-card' && oracleCards().some(card=>card.id===payload.id)){
      document.getElementById(payload.id)?.querySelector('button[aria-label=Edit]')?.click();
    }
    if(op==='save-card' && location.hostname==='jpmc.fa.oraclecloud.com' && payload.url===location.href){
      const buttons=[...document.querySelectorAll('button')].filter(e=>visible(e) && norm(e.innerText).toUpperCase()==='SAVE' && !e.disabled);
      if(buttons.length===1)buttons[0].click();
    }
    if(op==='location-search'||op==='location-select'){
      const e=locationInput();
      if(e && payload.value && op==='location-search'){
        e.focus();
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,payload.value);
        e.dispatchEvent(new Event('input',{bubbles:true}));
      }else if(e){
        const opts=[...(document.getElementById(e.id+'-list')?.querySelectorAll('[role=option]')||[])].filter(o=>visible(o)&&norm(o.innerText)===payload.value);
        if(opts.length===1){opts[0].click();filled.push('Location');}
      }
    }
    if(op==='accept-terms' && payload.url===location.href && location.hostname.endsWith('.oraclecloud.com')){
      const choices=elements().filter(e=>e.type==='checkbox' && /^i agree with the terms and conditions[.!* ]*$/i.test(label(e)) && !e.checked);
      if(choices.length===1){choices[0].click();if(choices[0].checked)filled.push('Terms and conditions');}
    }
    if(op==='entry' && payload.url===location.href) entryButton()?.click();
    if(op==='custom-open' || op==='custom-select') {
      const e=document.querySelector('[data-jobprep-id="'+payload.id+'"]');
      const list=e && document.getElementById(e.getAttribute('aria-controls') || e.getAttribute('aria-owns') || (e.closest('.select__control') && 'react-select-'+e.id+'-listbox'));
      const oracleGrid=e?.classList.contains('cx-select-input') && e.getAttribute('aria-haspopup')==='grid' && location.hostname.endsWith('.oraclecloud.com');
      if(oracleGrid && op==='custom-open'){
        e.focus();
        if(e.getAttribute('aria-expanded')!=='true')document.getElementById(e.id+'-toggle-button')?.click();
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,String(payload.value));
        e.dispatchEvent(new Event('input',{bubbles:true}));
        e.dispatchEvent(new KeyboardEvent('keyup',{key:'Unidentified',bubbles:true}));
      }else if(!e || e.getAttribute('role')!=='combobox' || (!list && op==='custom-select') || (e.tagName==='BUTTON' && e.type!=='button')) issues.push('Unsupported custom dropdown; select manually.');
      else if(op==='custom-open') {
        const control=e.closest('.select__control');
        if(control && !list){e.focus();e.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));if(e.getAttribute('aria-expanded')!=='true')control.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true,button:0}));}
        else e.click();
      }
      else {
        const matches=[...list.querySelectorAll(oracleGrid?'[role="gridcell"]':'[role="option"]')].filter(o=>visible(o)&&([payload.value,...(oracleGrid ? payload.aliases || [] : [])].some(v=>norm(o.innerText).toLowerCase()===String(v).toLowerCase()) || (e.id==='country' && norm(o.innerText).replace(/\s*\(\+?[\d -]+\)$/, '').toLowerCase()===String(payload.value).toLowerCase())) && (o.tagName!=='BUTTON'||o.type==='button'));
        if(matches.length===1){matches[0].click();filled.push(label(e));}else issues.push('No unique custom dropdown option; select manually.');
      }
    }
    if(op==='fill') for(const a of payload.answers || []) {
      const e = document.querySelector('[data-jobprep-id="'+a.id+'"]');
      if(!e || !visible(e) || e.disabled || e.readOnly) continue;
      if(/agree|accept|acknowledge|confirm|certify|consent|signature|declaration|terms|attest|privacy|policy/i.test(label(e))) {issues.push('Legal declaration requires your action.');continue;}
      if(e.matches('button[type=button][role=radio]')){
        const group=e.closest('[role=radiogroup]');
        if(a.checked && group && !group.querySelector('[aria-checked=true]') && !e.matches('[aria-disabled=true]')){
          e.click();if(e.getAttribute('aria-checked')==='true')filled.push(group.getAttribute('aria-label') || label(e));
        }
        continue;
      }
      if(e.type==='file') continue;
      // Preserve populated fields, including user edits on retries.
      if((e.type==='checkbox'||e.type==='radio') ? e.checked : !!e.value) continue;
      if(e.getAttribute('role')==='combobox' && e.tagName!=='SELECT') {issues.push(label(e)+': custom control needs manual selection.');continue;}
      if(e.type==='radio'||e.type==='checkbox') {
        if(a.checked===true){e.click();if(e.checked)filled.push(label(e));}continue;
      } else {
        const proto = e.tagName==='SELECT'?HTMLSelectElement.prototype:e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto,'value').set.call(e,String(a.value));
      }
      e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));
      filled.push(label(e));
    }
    if(op==='upload') {
      const e=document.querySelector('[data-jobprep-id="'+payload.id+'"]');
      if(e?.type==='file' && !e.files.length) {
        const bytes=Uint8Array.from(atob(payload.base64),c=>c.charCodeAt(0));
        const dt=new DataTransfer();dt.items.add(new File([bytes],payload.name,{type:payload.mime}));
        e.files=dt.files;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));
        filled.push('Resume file selected; acceptance still requires verification');
      }
    }
    // Only our audited local fixture has a permitted intermediate action. Unknown sites require user navigation.
    if(op==='next' && location.hostname==='127.0.0.1' && document.documentElement.dataset.jobprepFixture==='multi') {
      const b=document.querySelector('button[type="button"][data-jobprep-next]');if(b) b.click();
    }
  } finally {
    document.removeEventListener('submit',stop,true);HTMLFormElement.prototype.submit=oldSubmit;HTMLFormElement.prototype.requestSubmit=oldRequest;
  }
  return JSON.stringify({filled,issues});
})()
