(()=>{
  const header=document.querySelector('.site-header');
  const toggle=document.querySelector('.nav-toggle');
  const nav=document.querySelector('.site-nav');
  const year=document.getElementById('year');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;

  if(year) year.textContent=new Date().getFullYear();

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
  if('IntersectionObserver' in window){
    const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
      if(entry.isIntersecting){
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    }),{threshold:.08,rootMargin:'0px 0px -32px'});
    reveals.forEach(el=>observer.observe(el));
  }else reveals.forEach(el=>el.classList.add('visible'));

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
      if(matchMedia('(pointer:fine)').matches && !el.classList.contains('agent-grid')){
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
