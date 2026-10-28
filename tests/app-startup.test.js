const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');

async function harness({hosted=false,clipboard,legacyCopy,eventsFail=false,storedToken='',stateError=null,stateHang=false}={}){
 const elements=new Map();const calls=[];const timeouts=[];const timers=[];const listeners={};
 const element=selector=>{
  if(!elements.has(selector))elements.set(selector,{innerHTML:'',textContent:'',value:'',type:'password',open:false,dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},focus(){this.focused=true;},select(){this.selected=true;},setSelectionRange(start,end){this.selection=[start,end];}});
  return elements.get(selector);
 };
 const map=new Map(storedToken?[['ultron-token',storedToken]]:[]);
 const storage={getItem:key=>map.get(key)||null,setItem:(key,value)=>map.set(key,value)};
 const document={querySelector:element,querySelectorAll:()=>[],addEventListener(type,listener){listeners[type]=listener;},documentElement:{dataset:{}},execCommand:legacyCopy};
 const context=vm.createContext({document,navigator:{clipboard},location:{origin:hosted?'https://luke79210-hue.github.io':'http://127.0.0.1:8765',hostname:hosted?'luke79210-hue.github.io':'127.0.0.1',hash:''},window:{addEventListener(){}},sessionStorage:storage,localStorage:{getItem:()=>null,setItem(){}},matchMedia:()=>({matches:false}),setInterval(){},setTimeout(fn,ms){timeouts.push(ms);timers.push(fn);return timeouts.length;},clearTimeout(){},AbortSignal,AbortController,URL,Blob,console,
  fetch:async url=>{
   calls.push(url);
   if(url.endsWith('/api/session'))return {ok:true,json:async()=>({token:'fixture-session-token'})};
   if(url.endsWith('/api/state')&&stateHang)return new Promise(()=>{});
   if(url.endsWith('/api/state')&&stateError)throw stateError;
   if(url.endsWith('/api/state'))return {ok:true,json:async()=>({mode:'mock',devices:[],tasks:[],apks:[],package:'com.ultron.app'})};
   if(url.endsWith('/api/events'))return {ok:!eventsFail,status:503,json:async()=>eventsFail?{error:'history unavailable'}:[]};
   throw new Error('Unexpected URL '+url);
  }});
 vm.runInContext(source,context);
 await new Promise(resolve=>setImmediate(resolve));
 return {context,elements,element,calls,timeouts,timers,listeners};
}

test('裝置預設單選，明確開啟多台螢幕選擇後可多選，關閉時恢復單選',async()=>{
 const app=await harness();
 vm.runInContext('render=()=>{}; selected=new Set(["first"]);',app.context);
 const click=id=>app.listeners.click({target:{closest:()=>({dataset:{chip:id}})}});
 const selected=()=>Array.from(vm.runInContext('[...selected]',app.context));
 await click('second');assert.deepEqual(selected(),['second']);
 await click('second');assert.deepEqual(selected(),['second']);
 vm.runInContext('handlers["multi-device-select"]()',app.context);
 assert.equal(vm.runInContext('multiScreen',app.context),true);
 await click('third');assert.deepEqual(selected(),['second','third']);
 await click('second');assert.deepEqual(selected(),['third']);
 await click('first');
 vm.runInContext('handlers["multi-device-select"]()',app.context);
 assert.deepEqual(selected(),['third']);
 assert.equal(vm.runInContext('multiScreen',app.context),false);
 await click('first');assert.deepEqual(selected(),['first']);
});

test('本機啟動完整載入 session、裝置與活動，不能再因缺少 loadEvents 退回錯誤頁',async()=>{
 const app=await harness();
 assert.deepEqual(app.calls.map(url=>new URL(url).pathname),['/api/session','/api/state','/api/events']);
 assert.match(app.element('#main').innerHTML,/裝置列表/);
 assert.doesNotMatch(app.element('#main').innerHTML,/loadEvents is not defined|connection-error/);
});
test('正式網站使用已配對權杖直接載入管理平台，不跨來源讀取本機 session',async()=>{
 const app=await harness({hosted:true,storedToken:'fixture-paired-token'});
 assert.deepEqual(app.calls.map(url=>new URL(url).pathname),['/api/state','/api/events']);
 assert.match(app.element('#main').innerHTML,/裝置列表/);
});
test('歷史紀錄 API 失敗不應中斷已成功的設備連線',async()=>{
 const app=await harness({eventsFail:true});
 assert.match(app.element('#main').innerHTML,/裝置列表/);
 assert.doesNotMatch(app.element('#main').innerHTML,/connection-error/);
});
test('剪貼簿可用時複製設定欄內的權杖，不能複製過期的全域值',async()=>{
 const copied=[];
 const app=await harness({clipboard:{writeText:async value=>copied.push(value)}});
 app.element('#settings-token').value='fixture-field-token';
 await vm.runInContext('copyPairingToken()',app.context);
 assert.deepEqual(copied,['fixture-field-token']);
 assert.match(app.element('#token-copy-status').textContent,/已複製/);
});
test('剪貼簿權限遭拒時使用備援，且成功後恢復遮蔽',async()=>{
 let legacyCalls=0;
 const app=await harness({clipboard:{writeText:async()=>{throw new Error('permission denied');}},legacyCopy:()=>{legacyCalls++;return true;}});
 app.element('#settings-token').value='fixture-token';
 await vm.runInContext('copyPairingToken()',app.context);
 assert.equal(legacyCalls,1);
 assert.equal(app.element('#settings-token').type,'password');
 assert.match(app.element('#token-copy-status').textContent,/備援/);
});
test('兩種複製方式皆不支援時顯示並選取權杖，明確要求手動複製，不宣稱成功',async()=>{
 const app=await harness({legacyCopy:()=>false});
 const field=app.element('#settings-token');field.value='  fixture-token  ';
 await vm.runInContext('copyPairingToken()',app.context);
 assert.equal(field.type,'text');assert.equal(field.selected,true);assert.equal(field.value,'fixture-token');assert.deepEqual(field.selection,[0,13]);
 assert.match(app.element('#token-copy-status').textContent,/手動複製/);
 assert.doesNotMatch(app.element('#toast').textContent,/已複製/);
});
test('空權杖不可覆寫剪貼簿或顯示成功',async()=>{
 let calls=0;
 const app=await harness({clipboard:{writeText:async()=>calls++}});
 app.element('#settings-token').value='';
 await assert.rejects(()=>vm.runInContext('copyPairingToken()',app.context),/尚未取得/);
 assert.equal(calls,0);
});

test('配對檢查最多等待 10 秒，逾時有明確提示且不再請求歷史 API',async()=>{
 const error=new Error('timeout');error.name='TimeoutError';
 const app=await harness({hosted:true,storedToken:'fixture-paired-token',stateError:error});
 assert.deepEqual(app.calls.map(url=>new URL(url).pathname),['/api/state']);
 assert.equal(app.timeouts[0],10000);
 assert.match(app.element('#main').innerHTML,/連線逾時/);
 assert.match(app.element('#main').innerHTML,/已允許此網站存取本機/);
});
test('瀏覽器拒絕本機連線時給出錯誤及本機頁面備援，不宣稱配對成功',async()=>{
 const app=await harness({hosted:true,storedToken:'fixture-paired-token',stateError:new TypeError('Failed to fetch')});
 assert.match(app.element('#main').innerHTML,/無法連接本機服務/);
 assert.match(app.element('#main').innerHTML,/http:\/\/127.0.0.1:8765/);
 assert.doesNotMatch(app.element('#main').innerHTML,/裝置列表/);
});

test('即使瀏覽器 fetch 忽略 AbortSignal 且不回應，獨立逾時計時仍會結束配對等待',async()=>{
 const app=await harness({hosted:true,storedToken:'fixture-paired-token',stateHang:true});
 const timer=app.timers[app.timeouts.indexOf(10000)];
 assert.equal(typeof timer,'function');timer();
 await new Promise(resolve=>setImmediate(resolve));
 assert.match(app.element('#main').innerHTML,/連線逾時/);
 assert.deepEqual(app.calls.map(url=>new URL(url).pathname),['/api/state']);
});

test('連線失敗時保留已貼上的權杖，空值重試不得清除原 session',async()=>{
 const app=await harness({hosted:true,storedToken:'fixture-paired-token',stateError:new TypeError('Failed to fetch')});
 assert.match(app.element('#main').innerHTML,/value="fixture-paired-token"/);
 await assert.rejects(()=>vm.runInContext("pair('http://127.0.0.1:8765','')",app.context),/請先貼上/);
 assert.equal(vm.runInContext('token',app.context),'fixture-paired-token');
 assert.deepEqual(app.calls.map(url=>new URL(url).pathname),['/api/state']);
});
