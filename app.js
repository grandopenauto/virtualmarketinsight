(()=>{
  const header=document.querySelector('.site-header');
  const toggle=document.querySelector('.nav-toggle');
  const nav=document.querySelector('.site-nav');
  const year=document.getElementById('year');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const API='https://api.virtualmarketinsight.com';

  if(year) year.textContent=new Date().getFullYear();

  if(!document.querySelector('link[href="router.css"]')){
    const routerCss=document.createElement('link');
    routerCss.rel='stylesheet';
    routerCss.href='router.css';
    document.head.appendChild(routerCss);
  }

  const progress=document.createElement('div');
  progress.className='scroll-progress';
  progress.setAttribute('aria-hidden','true');
  document.body.appendChild(progress);

  const onScroll=()=>{
    header?.classList.toggle('scrolled',scrollY>16);
    const doc=document.documentElement;
    const max=doc.scrollHeight-innerHeight;
    progress.style.width=max>0?`${Math.min(100,(scrollY/max)*100)}%`:'0%';
  };
  onScroll();
  addEventListener('scroll',onScroll,{passive:true});

  toggle?.addEventListener('click',()=>{
    const open=nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded',String(open));
  });
  nav?.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{
    nav.classList.remove('open');
    toggle?.setAttribute('aria-expanded','false');
  }));

  const reveals=[...document.querySelectorAll('.reveal')];
  reveals.forEach((el,i)=>el.style.transitionDelay=`${Math.min(i%4,3)*55}ms`);
  if('IntersectionObserver'in window){
    const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
      if(entry.isIntersecting){
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    }),{threshold:.08,rootMargin:'0px 0px -32px'});
    reveals.forEach(el=>observer.observe(el));
  }else reveals.forEach(el=>el.classList.add('visible'));

  const surfaces=[
    ['markets','Markets'],
    ['analyst','Analyst'],
    ['opportunities','Opportunities'],
    ['operational-capital','Operational Capital'],
    ['agents','Agents']
  ];
  const surfaceHash={
    'markets':'#markets',
    'analyst':'#analyst',
    'opportunities':'#opportunities',
    'operational-capital':'#operational-capital',
    'agents':'#agents'
  };
  let startingSurface=null;

  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  document.body.insertAdjacentHTML('beforeend',`
    <div class="vmi-router-backdrop" id="vmi-router-backdrop" aria-hidden="true"></div>
    <aside class="vmi-router" id="vmi-router" aria-labelledby="vmi-router-title" aria-hidden="true">
      <div class="vmi-router-head">
        <div>
          <span class="vmi-router-kicker">VMI Intelligent Front Door</span>
          <h2 id="vmi-router-title">What are you trying to do?</h2>
          <p>Start with the question. VMI will map the right entry point and capability path.</p>
        </div>
        <button class="vmi-router-close" type="button" aria-label="Close VMI router">×</button>
      </div>
      <div class="vmi-router-body">
        <div class="vmi-router-status" id="vmi-router-status"><i></i><span>Checking public gateway…</span></div>
        <div class="vmi-router-surfaces" id="vmi-router-surfaces">
          ${surfaces.map(([id,label])=>`<button type="button" class="vmi-router-chip" data-surface="${id}">${label}</button>`).join('')}
        </div>
        <form id="vmi-router-form">
          <label class="vmi-router-label" for="vmi-router-query">YOUR QUESTION OR OBJECTIVE</label>
          <textarea id="vmi-router-query" maxlength="2000" required placeholder="Example: I am looking at data-center growth. What is driving it, what constraints matter, and where are the operating opportunities behind the trend?"></textarea>
          <div class="vmi-router-actions">
            <button class="button button-primary" type="submit">Map my request <span aria-hidden="true">↗</span></button>
            <span class="vmi-router-note">No external action is triggered here.</span>
          </div>
        </form>
        <div class="vmi-router-result" id="vmi-router-result" hidden></div>
      </div>
    </aside>
  `);

  const router=document.getElementById('vmi-router');
  const backdrop=document.getElementById('vmi-router-backdrop');
  const closeButton=router.querySelector('.vmi-router-close');
  const form=document.getElementById('vmi-router-form');
  const queryBox=document.getElementById('vmi-router-query');
  const result=document.getElementById('vmi-router-result');
  const status=document.getElementById('vmi-router-status');
  const chips=[...document.querySelectorAll('.vmi-router-chip')];

  const setSurface=id=>{
    startingSurface=id||null;
    chips.forEach(chip=>chip.classList.toggle('active',chip.dataset.surface===startingSurface));
  };

  const openRouter=(surface=null,seed='')=>{
    setSurface(surface);
    if(seed&&!queryBox.value.trim()) queryBox.value=seed;
    router.classList.add('open');
    backdrop.classList.add('open');
    router.setAttribute('aria-hidden','false');
    backdrop.setAttribute('aria-hidden','false');
    document.body.style.overflow='hidden';
    setTimeout(()=>queryBox.focus(),180);
  };

  const closeRouter=()=>{
    router.classList.remove('open');
    backdrop.classList.remove('open');
    router.setAttribute('aria-hidden','true');
    backdrop.setAttribute('aria-hidden','true');
    document.body.style.overflow='';
  };

  chips.forEach(chip=>chip.addEventListener('click',()=>setSurface(chip.dataset.surface)));
  closeButton.addEventListener('click',closeRouter);
  backdrop.addEventListener('click',closeRouter);
  addEventListener('keydown',e=>{if(e.key==='Escape'&&router.classList.contains('open')) closeRouter();});

  const cardMap={
    '#markets':'markets',
    '#analyst':'analyst',
    '#opportunities':'opportunities',
    '#operational-capital':'operational-capital',
    '#agents':'agents'
  };
  document.querySelectorAll('.entry-card').forEach(card=>{
    const surface=cardMap[card.getAttribute('href')];
    if(!surface) return;
    card.classList.add('vmi-route-enabled');
    card.addEventListener('click',e=>{
      e.preventDefault();
      const title=card.querySelector('h3')?.textContent?.trim()||'';
      openRouter(surface,title?`I want to ${title.toLowerCase()}. `:'');
    });
  });

  document.querySelectorAll('a[href="#enter"]').forEach(link=>{
    link.addEventListener('click',e=>{e.preventDefault();openRouter();});
  });

  fetch(`${API}/health`,{headers:{accept:'application/json'}})
    .then(r=>{if(!r.ok) throw new Error('offline');return r.json();})
    .then(data=>{
      status.classList.add('online');
      status.querySelector('span').textContent=`Public gateway online · v${data.version}`;
    })
    .catch(()=>{status.querySelector('span').textContent='Router ready · gateway check unavailable';});

  form.addEventListener('submit',async e=>{
    e.preventDefault();
    const query=queryBox.value.trim();
    if(query.length<3) return;
    form.classList.add('vmi-router-loading');
    result.hidden=false;
    result.innerHTML='<div class="vmi-route-summary"><small>Mapping request</small><h3>Building capability path…</h3><p>Classifying the starting point and execution graph.</p></div>';
    try{
      const response=await fetch(`${API}/api/v1/router/resolve`,{
        method:'POST',
        headers:{'content-type':'application/json','accept':'application/json'},
        body:JSON.stringify({query,starting_surface:startingSurface})
      });
      if(!response.ok) throw new Error(`Gateway returned ${response.status}`);
      const data=await response.json();
      const graph=(data.graph_path||[]).map((step,i)=>`${i?'<i>→</i>':''}<span>${esc(step)}</span>`).join('');
      const capabilities=(data.capability_plan||[]).map(cap=>`<div class="vmi-cap"><b>${esc(cap.name)}</b><span>${esc(cap.role)}</span></div>`).join('');
      const hash=surfaceHash[data.resolved_surface]||'#entry-points';
      const signals=(data.signals||[]).length?` · ${esc(data.signals.join(', '))}`:'';
      result.innerHTML=`
        <div class="vmi-route-summary">
          <small>${esc(data.match_level)} routing match${signals}</small>
          <h3>${esc(data.label)}</h3>
          <p>VMI selected this as the best public starting point for the request.</p>
        </div>
        <div class="vmi-route-graph">${graph}</div>
        <div class="vmi-cap-list">${capabilities}</div>
        <div class="vmi-route-next"><b>Next:</b> ${esc(data.next_action)}</div>
        <div class="vmi-route-footer"><span class="vmi-router-note">External actions executed: ${esc(data.external_actions_executed)}</span><a href="${hash}" class="vmi-view-section">View this VMI surface →</a></div>
        <p class="vmi-authority">${esc(data.authority_notice)}</p>
      `;
      result.querySelector('.vmi-view-section')?.addEventListener('click',closeRouter);
    }catch(err){
      result.innerHTML=`<div class="vmi-route-summary"><small>Gateway unavailable</small><h3>The public router could not be reached.</h3><p>${esc(err.message)}. The presentation site remains available; no external action was attempted.</p></div>`;
    }finally{
      form.classList.remove('vmi-router-loading');
    }
  });

  if(reduced) return;

  const heroGraph=document.getElementById('hero-graph');
  const orbit=document.querySelector('.market-orbit');
  const glow=document.querySelector('.hero-glow');
  if(orbit&&heroGraph){
    orbit.addEventListener('pointermove',e=>{
      const r=orbit.getBoundingClientRect();
      const x=(e.clientX-r.left)/r.width;
      const y=(e.clientY-r.top)/r.height;
      orbit.style.setProperty('--mx',`${x*100}%`);
      orbit.style.setProperty('--my',`${y*100}%`);
      heroGraph.style.transform=`translate(${(x-.5)*9}px,${(y-.5)*9}px) scale(1.008)`;
      orbit.style.transform=`perspective(1100px) rotateX(${(.5-y)*2.4}deg) rotateY(${(x-.5)*2.8}deg)`;
    });
    orbit.addEventListener('pointerleave',()=>{
      heroGraph.style.transform='';
      orbit.style.transform='';
    });
  }

  addEventListener('pointermove',e=>{
    if(!glow) return;
    const x=(e.clientX/innerWidth-.5)*18;
    const y=(e.clientY/innerHeight-.5)*14;
    glow.style.transform=`translate(${x}px,${y}px)`;
  },{passive:true});

  const reactive=[...document.querySelectorAll('.entry-card,.market-panel,.terminal,.opportunity-card,.stack-card,.agent-grid>div')];
  reactive.forEach(el=>{
    el.classList.add('reactive-card');
    el.addEventListener('pointermove',e=>{
      const r=el.getBoundingClientRect();
      const x=(e.clientX-r.left)/r.width;
      const y=(e.clientY-r.top)/r.height;
      el.style.setProperty('--mx',`${x*100}%`);
      el.style.setProperty('--my',`${y*100}%`);
      if(matchMedia('(pointer:fine)').matches&&!el.classList.contains('agent-grid')){
        const rx=(.5-y)*1.25;
        const ry=(x-.5)*1.5;
        el.style.transform=`perspective(1200px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-1px)`;
      }
    });
    el.addEventListener('pointerleave',()=>{el.style.transform='';});
  });

  const map=document.querySelector('.market-map');
  if(map){
    const nodes=[...map.querySelectorAll('.market-node')];
    map.addEventListener('pointermove',e=>{
      const r=map.getBoundingClientRect();
      const x=e.clientX-r.left-r.width/2;
      const y=e.clientY-r.top-r.height/2;
      nodes.forEach((node,i)=>{
        const strength=node.classList.contains('primary')?0.018:0.008+(i%3)*0.003;
        node.style.marginLeft=`${x*strength}px`;
        node.style.marginTop=`${y*strength}px`;
      });
    });
    map.addEventListener('pointerleave',()=>nodes.forEach(node=>{
      node.style.marginLeft='';
      node.style.marginTop='';
    }));
  }
})();
