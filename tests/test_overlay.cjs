// Run with node --test tests/test_overlay.cjs (Node 18+, no npm packages).
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=[...fs.readFileSync(path.join(__dirname,'../overlay.html'),'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const flush=()=>new Promise(r=>setImmediate(r));
function harness(){
 let now=0, nextId=0;
 const timers=new Map(), elements=new Map(), images=[], requests=[];
 const element=id=>{
  if(!elements.has(id)){
   const classes=new Set(); let text='',writes=0;
   elements.set(id,{style:{},offsetWidth:100,classList:{add:(...cs)=>cs.forEach(c=>classes.add(c)),remove:(...cs)=>cs.forEach(c=>classes.delete(c)),toggle:(c,on)=>on?classes.add(c):classes.delete(c),contains:c=>classes.has(c)},
    get textContent(){return text},set textContent(v){text=v;writes++},get textWrites(){return writes}});
  }
  return elements.get(id);
 };
 class Img {
  constructor(){images.push(this)}
  set src(v){this.url=v;this.cancelled=false}
  removeAttribute(name){if(name==='src')this.cancelled=true}
 }
 const sandbox=vm.createContext({document:{getElementById:element},window:{location:{href:'http://localhost/overlay.html'}},URL,Image:Img,AbortController,
  performance:{now:()=>now},setTimeout:(fn,ms)=>{const id=++nextId;timers.set(id,{fn,at:now+ms});return id},clearTimeout:id=>timers.delete(id),
  fetch:(url,{signal})=>new Promise((resolve,reject)=>{const r={url,signal,resolve,reject};requests.push(r);signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true})})});
 vm.runInContext(source+'\nthis.NP=NowPlaying;',sandbox);
 return {sandbox,images,requests,element,timers,async advance(ms){
  const end=now+ms;
  for(let count=0;count<10000;count++){
   const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
   if(!next){now=end;await flush();return}
   now=next[1].at;timers.delete(next[0]);next[1].fn();await flush();
  }
  throw new Error('timer loop');
 }};
}
const track=(extra={})=>({key:'Song',title:'Song',artist:'Artist',album:'Album',state:'paused',current:1,duration:240,art:'/runtime/cover_1.jpg?v=a',...extra});

test('progress follows video speed, speed changes, pause and seek',async()=>{
 const h=harness();
 h.sandbox.NP.update(track({state:'playing',current:10,playbackRate:2,art:''}));
 await h.advance(1000);assert.equal(h.element('cur').textContent,'0:12');
 h.sandbox.NP.update(track({state:'playing',current:12,playbackRate:.5,art:''}));
 await h.advance(2000);assert.equal(h.element('cur').textContent,'0:13');
 h.sandbox.NP.update(track({state:'paused',current:13,playbackRate:0,art:''}));
 await h.advance(1000);assert.equal(h.element('cur').textContent,'0:13');
 h.sandbox.NP.update(track({state:'playing',current:2,playbackRate:1,art:''}));
 await h.advance(1000);assert.equal(h.element('cur').textContent,'0:03');
});

test('runtime forwards playback speed and distinguishes matching titles across apps',async()=>{
 const h=harness();
 const payload={title:'Video',artist:'Channel',album:'',state:'playing',position:10,duration:100,
  playbackRate:2,sourceAppId:'com.google.Chrome',trackId:'one'};
 h.requests[0].resolve({ok:true,json:async()=>payload});await flush();
 await h.advance(1000);assert.equal(h.element('cur').textContent,'0:12');
 h.requests[1].resolve({ok:true,json:async()=>({...payload,position:0,sourceAppId:'com.apple.Safari'})});
 await flush();assert(h.element('title').classList.contains('swap-out'));
 assert.equal(h.element('cur').textContent,'0:00');
});

test('polling has one request including manual overlaps; aborts and resumes',async()=>{
 const h=harness();for(let i=0;i<120;i++)h.sandbox.updateFromRuntime();
 assert.equal(h.requests.length,1);
 await h.advance(5000);assert(h.requests[0].signal.aborted);
 await h.advance(250);assert.equal(h.requests.length,2);
 h.requests[1].resolve({ok:true,json:async()=>({title:'New song',state:'paused',duration:240})});
 await flush();assert.equal(h.element('title').textContent,'New song');
});

test('timeout remains active during response body decoding',async()=>{
 const h=harness();const r=h.requests[0];
 r.resolve({ok:true,json:()=>new Promise((resolve,reject)=>r.signal.addEventListener('abort',()=>reject(new Error('body aborted'))))});
 await flush();await h.advance(5000);await h.advance(250);
 assert.equal(h.requests.length,2);
});

test('same artwork is single flight; cancellation prevents a stale commit',()=>{
 const h=harness();for(let i=0;i<40;i++)h.sandbox.NP.update(track());
 assert.equal(h.images.length,1);
 const stale=h.images[0].onload;
 h.sandbox.NP.update(track({key:'Other',art:'/runtime/cover_0.jpg?v=b'}));
 assert(h.images[0].cancelled);assert.equal(h.images.length,2);
 h.images[1].onload();stale();
 assert(h.element('art1').style.backgroundImage.includes('v=b'));
});

test('return to visible artwork cancels a pending different artwork',()=>{
 const h=harness();h.sandbox.NP.update(track());h.images[0].onload();
 h.sandbox.NP.update(track({art:'/runtime/cover_0.jpg?v=b'}));
 const stale=h.images[1].onload;h.sandbox.NP.update(track());stale();
 assert(h.images[1].cancelled);assert(h.element('art0').style.backgroundImage.includes('v=a'));
});

test('content version change on the same track is loaded',()=>{
 const h=harness();h.sandbox.NP.update(track());h.images[0].onload();
 h.sandbox.NP.update(track({art:'/runtime/cover_1.jpg?v=b'}));
 assert.equal(h.images.length,2);h.images[1].onload();
 assert(h.element('art1').style.backgroundImage.includes('v=b'));
});

test('hung artwork times out and retries with bounded frequency',async()=>{
 const h=harness();h.sandbox.NP.update(track());await h.advance(5000);
 assert(h.images[0].cancelled);
 for(let i=0;i<40;i++)h.sandbox.NP.update(track());assert.equal(h.images.length,1);
 await h.advance(5000);h.sandbox.NP.update(track());assert.equal(h.images.length,2);
});

test('text animation cannot restore an old playback state or position',async()=>{
 const h=harness();h.sandbox.NP.update(track({art:''}));
 h.sandbox.NP.update(track({key:'New',current:1,state:'playing',art:''}));
 h.sandbox.NP.update(track({key:'New',current:42,state:'paused',art:''}));
 await h.advance(1000);
 assert.equal(h.element('cur').textContent,'0:42');
 assert.equal(h.element('filled').style.clipPath,'inset(0 82.5% 0 0 round 3px)');
});

test('progress updates text only when displayed seconds change',async()=>{
 const h=harness();h.sandbox.NP.update(track({state:'playing',art:''}));
 const writes=h.element('cur').textWrites, durationWrites=h.element('dur').textWrites;
 await h.advance(900);
 assert.equal(h.element('cur').textWrites,writes);
 assert.equal(h.element('dur').textWrites,durationWrites);
 await h.advance(100);assert.equal(h.element('cur').textContent,'0:02');
});

test('faded-out artwork is released after transition',async()=>{
 const h=harness();h.sandbox.NP.update(track());h.images[0].onload();
 h.sandbox.NP.update(track({key:'New',art:'/runtime/cover_0.jpg?v=b'}));h.images[1].onload();
 await h.advance(900);
 assert.equal(h.element('art0').style.backgroundImage,'');
 assert.equal(h.element('amb0').style.backgroundImage,'');
});

test('pending metadata keeps a shared cover without reloading; a missing result clears it',async()=>{
 const h=harness();
 const data={title:'First',state:'playing',position:1,duration:240,artworkFile:'cover_a.jpg',artworkVersion:'a'};
 const respond=async d=>{h.requests.at(-1).resolve({ok:true,json:async()=>d});await flush()};
 await respond(data);h.images[0].onload();
 const visible=h.element('art0').style.backgroundImage;
 await h.advance(250);
 await respond({...data,title:'Second',artworkFile:'',artworkPending:true});
 assert.equal(h.element('art0').style.backgroundImage,visible);
 assert.equal(h.images.length,1);
 await h.advance(250);await respond({...data,title:'Second',artworkPending:false});
 assert.equal(h.images.length,1);
 assert.equal(h.element('art0').style.backgroundImage,visible);
 await h.advance(250);await respond({...data,title:'Second',artworkFile:'',artworkPending:false});
 assert(h.element('art1').style.backgroundImage.includes('data:image/svg'));
});

test('a slow lookup stops showing the previous cover after the grace period',async()=>{
 const h=harness();h.sandbox.NP.update(track({state:'playing'}));h.images[0].onload();
 const pending=track({key:'New',title:'New',state:'playing',art:undefined});
 h.sandbox.NP.update(pending);
 await h.advance(2400);h.sandbox.NP.update(pending);
 assert(h.element('art0').classList.contains('active'),'cover is kept while the lookup is quick');
 await h.advance(100);h.sandbox.NP.update(pending);
 assert(h.element('art1').style.backgroundImage.includes('data:image/svg'));
 assert(h.element('art1').classList.contains('active'));
 h.sandbox.NP.update(track({key:'New',title:'New',state:'playing',art:'/runtime/cover_0.jpg?v=b'}));
 h.images[1].onload();
 assert(h.element('art0').style.backgroundImage.includes('v=b'));
});

test('artwork retries on the same track never replace a resolved cover',async()=>{
 const h=harness();h.sandbox.NP.update(track({state:'playing'}));h.images[0].onload();
 const retrying=track({state:'playing',art:undefined});
 for(let i=0;i<5;i++){await h.advance(3000);h.sandbox.NP.update(retrying)}
 assert(h.element('art0').style.backgroundImage.includes('v=a'));
 assert(h.element('art0').classList.contains('active'));
});

test('stopping during the text swap still shows the new track',async()=>{
 const h=harness();h.sandbox.NP.update(track({art:''}));
 h.sandbox.NP.update(track({key:'New',title:'New',artist:'Other',art:''}));
 assert.equal(h.element('title').textContent,'Song');
 h.sandbox.NP.update({state:'stopped'});
 assert.equal(h.element('title').textContent,'New');
 assert.equal(h.element('meta').textContent,'Other \u00b7 Album');
 await h.advance(1000);
 assert.equal(h.element('title').textContent,'New');
});
