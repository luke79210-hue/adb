'use strict';
const $ = (s,root=document)=>root.querySelector(s);
const $$ = (s,root=document)=>[...root.querySelectorAll(s)];
const esc = v=>String(v??'待驗證').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {devices:'裝置資訊',console:'主控台',apks:'APK 版本資料庫'};
const actionNames = {key:'遙控按鍵',restart_app:'重啟奧創 APP',reboot:'重啟設備',shutdown:'設備關機',clear_data:'清除 APP 資料',factory_reset:'設備原廠重置',set_time:'設定設備時間',network_time:'恢復網路時間',install:'安裝 APK',record:'30 秒錄影'};
const statusNames = {queued:'等待中',running:'執行中',cancelling:'取消中',cancelled:'已取消',succeeded:'已完成',failed:'失敗',interrupted:'已中斷'};
const risky = new Set(['reboot','shutdown','clear_data','factory_reset','install']);
let apiBase = localStorage.getItem('ultron-api')||((location.hostname==='127.0.0.1'||location.hostname==='localhost')?location.origin:'http://127.0.0.1:8765');
let token = sessionStorage.getItem('ultron-token')||'';
let page = location.hash.slice(1) in labels?location.hash.slice(1):'devices';
let state = {devices:[],tasks:[],apks:[],mode:'mock'}, selected = new Set(), events = [], online = false;
let deviceSearch='', deviceStatus='all', multiScreen=false, screenStreaming=true;
let logLines=[], logIds=new Set(), logDevice='', logPaused=false, logQuery='', logLevel='all', logApp='all';
let logController=null;
let stateBusy=false, logBusy=false, screenBusy=false, screenURLs=new Map(), toastTimer, modalResolver=null;
const isMock=()=>state.mode==='mock';
const chosen=()=>state.devices.filter(d=>selected.has(d.id));
const fmtTime = t=>t?new Date(t).toLocaleString('zh-TW',{hour12:false}):'待驗證';
const fmtSize = s=>(s/1024/1024).toFixed(1)+' MB';
const connected = d=>d.adb==='connected';
const badge = (text,style='')=>`<span class="pill ${style}">${esc(text)}</span>`;
const empty = text=>`<div class="empty">${esc(text)}</div>`;
const mockNotice = ()=>isMock()?`<div class="notice"><span>◈</span><strong>模擬模式</strong><span>ADB 裝置與操作皆為展示資料；Google Drive 按鈕需另設真實憑證，且會操作公司雲端。</span><span class="notice-right">DEMO ENVIRONMENT</span></div>`:'';
function toast(message,error=false){const el=$('#toast');el.textContent=message;el.className='visible'+(error?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.className='',6500);}
async function api(path,{method='GET',body,raw,filename,blob=false}={}){
 const headers={'X-Ultron-Token':token};if(body!==undefined)headers['Content-Type']='application/json';if(filename)headers['X-Filename']=encodeURIComponent(filename);
 const response=await fetch(apiBase+path,{method,headers,body:raw??(body===undefined?undefined:JSON.stringify(body)),signal:AbortSignal.timeout(path.includes('/discover')?60000:250000)});
 if(!response.ok){let data;try{data=await response.json();}catch{data={error:'HTTP '+response.status};}throw new Error(data.error||'服務回應錯誤');}
 if(blob)return {blob:await response.blob(),disposition:response.headers.get('Content-Disposition')};
 return response.json();
}
async function post(path,body={}){return api(path,{method:'POST',body});}
function saveBlob(blob,name){const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),60000);}
async function download(path,fallback){const r=await api(path,{blob:true});const m=r.disposition?.match(/filename\*=UTF-8''(.+)/);saveBlob(r.blob,m?decodeURIComponent(m[1]):fallback);}
function showDialog(title,html,buttons=[{text:'關閉',value:'close'}]){
 if(modalResolver)modalResolver(null);
 $('#dialog-content').innerHTML=`<div class="dialog-head"><h2>${esc(title)}</h2><button class="icon-button" data-dialog-value="close" aria-label="關閉">×</button></div><div class="dialog-body">${html}</div><div class="dialog-footer">${buttons.map(b=>`<button class="${b.class||''}" data-dialog-value="${esc(b.value)}">${esc(b.text)}</button>`).join('')}</div>`;
 if(!$('#dialog').open)$('#dialog').showModal();
 return new Promise(resolve=>{modalResolver=resolve;});
}
function closeDialog(value){$('#dialog').close();const fn=modalResolver;modalResolver=null;fn?.(value);}
$('#dialog').addEventListener('cancel',()=>{const fn=modalResolver;modalResolver=null;fn?.(null);});
$('#dialog').addEventListener('click',e=>{const b=e.target.closest('[data-dialog-value]');if(b)closeDialog(b.dataset.dialogValue);});
function heading(title,subtitle,actions=''){return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${actions}</div></div>`;}
function deviceBadge(d){return badge(connected(d)?'● 已連線':'● 已斷線',connected(d)?'':'bad');}
function appBadge(d){return badge(({running:'運行中',stopped:'未啟動',not_installed:'未安裝',unknown:'待驗證'})[d.app]||'待驗證',d.app==='running'?'':'neutral');}
function usage(d,key){return d[key]==null?'<span class="muted">待驗證</span>':`<span class="mono">${esc(d[key])}%</span><div class="mini-bar"><span class="${d[key]>=90?'hot':''}" style="width:${Math.max(0,Math.min(100,Number(d[key])))}%"></span></div>`;}
function devicesPage(){
 const list=state.devices.filter(d=>(!deviceSearch||`${d.name} ${d.id} ${d.brand} ${d.store}`.toLowerCase().includes(deviceSearch.toLowerCase()))&&(deviceStatus==='all'||(connected(d)?'connected':'disconnected')===deviceStatus));
 const n=state.devices.length,active=state.devices.filter(connected).length,apps=state.devices.filter(d=>d.app==='running').length,alerts=state.devices.reduce((sum,d)=>sum+(d.alerts?.length||0)+(!connected(d)?1:0),0);
 return heading('裝置資訊','掌握每台裝置的即時狀態，讓測試從穩定連線開始。',`<button data-action="discover"><span class="discovery-icon" aria-hidden="true">⌕</span>　搜尋區域網路</button><button class="primary" data-action="connect">＋　連線裝置</button>`)+mockNotice()+
 `<section class="metrics" aria-label="設備概況">${[
 ['已登錄裝置',n,'台','▦','所有管理中的 Set-Top Box'],['ADB 連線',active,`/ ${n} 台`,'⌁',`<span class="good">● 連線正常</span> · ${n-active} 台離線`],['奧創 APP',apps,'台運行中','▷','APP 與 ADB 狀態獨立監控'],['待處理異常',alerts,'項','△',alerts?'請查看異常紀錄':'目前未偵測到異常']].map(([label,value,unit,icon,foot])=>`<div class="metric"><div class="metric-label">${label}<span class="metric-icon">${icon}</span></div><div class="metric-value">${value}<small>${unit}</small></div><div class="metric-foot">${foot}</div></div>`).join('')}</section>`+
 `<section class="panel"><div class="panel-header"><div><h2>裝置列表 <small>${n} 台裝置</small></h2></div><div class="actions"><label class="check-row"><input id="auto-refresh" type="checkbox" ${localStorage.getItem('ultron-auto')!=='off'?'checked':''}>每 10 秒更新</label><button data-action="refresh" class="text-button">⟳ 手動刷新</button></div></div><div class="toolbar"><div class="actions"><input class="search" id="device-search" placeholder="⌕　搜尋名稱、IP、品牌或店家" aria-label="搜尋裝置" value="${esc(deviceSearch)}"><select id="device-status" aria-label="連線狀態"><option value="all">全部連線狀態</option><option value="connected" ${deviceStatus==='connected'?'selected':''}>已連線</option><option value="disconnected" ${deviceStatus==='disconnected'?'selected':''}>已斷線</option></select></div><button class="text-button" data-action="open-console">主控台操作（${selected.size}） ↗</button></div><div class="table-wrap"><table><thead><tr><th><input type="checkbox" id="select-all" aria-label="選取所有設備" ${n&&selected.size===n?'checked':''}></th><th>裝置名稱 / Local IP</th><th>ADB 狀態</th><th>奧創 APP</th><th>APP 版本</th><th>CPU</th><th>RAM</th><th>儲存空間</th><th>品牌 / 店家</th><th>操作</th></tr></thead><tbody>${list.map(d=>`<tr><td><input type="checkbox" data-select="${esc(d.id)}" aria-label="選取 ${esc(d.name)}" ${selected.has(d.id)?'checked':''}></td><td><div class="device-title"><span class="device-symbol">▣</span><div><strong>${esc(d.name)}</strong><small class="mono">${esc(d.id)}</small></div></div></td><td>${deviceBadge(d)}</td><td>${appBadge(d)}</td><td><span class="mono">${esc(d.versionName)}</span><span class="sub">Code ${esc(d.versionCode)}</span></td><td>${usage(d,'cpu')}</td><td>${usage(d,'ram')}</td><td>${usage(d,'storage')}</td><td>${esc(d.brand||'尚未設定')}<span class="sub">${esc(d.store||'尚未設定')}</span></td><td><button class="link-button" data-detail="${esc(d.id)}">詳細資訊 ↗</button></td></tr>`).join('')}</tbody></table>${!list.length?empty('沒有符合條件的裝置；請手動連線或搜尋 LAN'):''}</div><div class="table-foot"><span>顯示 ${list.length} 台裝置 · 已選取 ${selected.size} 台</span><span>自動重連可於裝置詳細資訊調整</span></div></section>`+
 `<div class="health-grid"><section class="panel"><div class="panel-header"><h2>最近活動 <small>ACTIVITY</small></h2><button class="text-button" data-action="history">查看完整紀錄 ↗</button></div><div class="panel-body">${recentEvents()}</div></section><section class="panel"><div class="panel-header"><h2>工作空間狀態</h2>${badge('LOCAL SERVICE')}</div><div class="panel-body"><div class="status-line"><span>本機服務</span><span><span class="live-dot"></span>已連線</span></div><div class="status-line"><span>資料保存</span><span>本機 SQLite</span></div><div class="status-line"><span>操作存取</span><span>Loopback + Session token</span></div><div class="status-line"><span>Google Drive</span><span>需設定公司資料夾與 OAuth</span></div><div class="status-line"><span>畫面傳輸</span><span>ADB PNG 輪詢 · 無音訊</span></div></div></section></div>`;
}
function recentEvents(){return events.slice(0,4).map(e=>`<div class="event-line"><span class="event-dot ${e.kind.includes('fail')||e.kind==='alert'?'bad':''}"></span><div>${esc(eventLabel(e.kind))}<small class="sub">${esc((e.device?e.device+' · ':'')+e.detail.slice(0,75))}</small></div><time>${new Date(e.at).toLocaleTimeString('zh-TW',{hour12:false})}</time></div>`).join('')||empty('尚無操作紀錄');}
function eventLabel(kind){return ({service:'本機服務啟動',connect:'裝置連線',reconnected:'裝置重新連線',alert:'裝置異常',operation:'已建立操作任務',task_succeeded:'操作完成',task_failed:'操作失敗',task_cancelled:'任務已取消',cancel_requested:'已要求取消',device_edit:'裝置資料更新',apk_upload:'APK 已存入版本庫',drive_upload:'APK 已上傳 Drive',backup:'已備份資料庫',restore:'已還原資料庫',discovery:'區域網路搜尋',screenshot:'已保存截圖'})[kind]||kind;}
function deviceChips(){return state.devices.map(d=>`<button data-chip="${esc(d.id)}" class="device-chip ${selected.has(d.id)?'selected':''}"><span class="live-dot ${connected(d)?'':'off'}"></span>${esc(d.name)}<small>${esc(d.localIP)}</small></button>`).join('');}
function consolePage(){
 const list=chosen();if(!logDevice||!selected.has(logDevice))logDevice=list[0]?.id||'';
 return heading('主控台','同步控制、即時畫面與 Logcat，在同一個工作畫面完成。',`<span class="pill neutral">${selected.size} 台已選取</span><button data-action="select-connected">選取已連線設備</button>`)+mockNotice()+
 `<div class="console-select">${deviceChips()||'<span class="muted">請先在裝置資訊新增設備</span>'}</div><div class="console-grid">
 <section class="panel remote-panel"><div class="panel-header"><h2>遙控器</h2><small>REMOTE</small></div><div class="remote"><div><div class="remote-row"><button data-key="source">Source</button><button data-key="home"><span class="home-icon" aria-hidden="true">⌂</span> Home</button></div><div class="dpad"><span></span><button data-key="up" aria-label="上">↑</button><span></span><button data-key="left" aria-label="左">←</button><button class="ok" data-key="ok">OK</button><button data-key="right" aria-label="右">→</button><span></span><button data-key="down" aria-label="下">↓</button><span></span></div><div class="remote-row"><button data-key="back">返回</button><button data-key="volume_down">音量 −</button><button data-key="volume_up">音量 ＋</button></div></div><div class="digits">${[1,2,3,4,5,6,7,8,9,0].map(n=>`<button data-key="${n}">${n}</button>`).join('')}</div><div class="hint">⌨ 方向鍵 / Enter：導航與確認<br>Esc：返回 · H：Home · S：Source<br>0–9：數字 · ＋ / −：音量<br>輸入文字或開啟對話框時停用快捷鍵。</div></div></section>
 <div class="screen-column"><section class="panel"><div class="panel-header"><h2>Android 即時畫面</h2><div class="actions"><button class="text-button" data-action="screen-toggle">${screenStreaming?'Ⅱ 暫停':'▷ 繼續'}</button><button class="text-button" data-action="multi-screen">${multiScreen?'▣ 單畫面':'▦ 多畫面'}</button></div></div><div class="screen-grid ${multiScreen?'multi':''}" id="screen-grid">${screenMarkup()}</div><div class="screen-actions"><button data-action="screenshot">▣ 截圖另存</button><button data-job="record">● 錄影 30 秒</button><button data-action="fullscreen">⛶ 全螢幕</button></div><div class="log-footer">${isMock()?'模擬預覽 · 非真實設備畫面 · 匯出 PNG 會保留模擬標示':'約 1.5 秒 PNG 輪詢 · 非影片串流 · 不含音訊 · 截圖與錄影會先保存至本機'}</div></section>
 <section class="panel"><div class="panel-header"><h2>ADB 操作</h2><small>作用於 ${selected.size} 台設備</small></div><div class="section-inner"><div class="operation-grid">${['restart_app','reboot','shutdown','clear_data','factory_reset'].map(a=>`<button class="${risky.has(a)?'danger':''}" data-job="${a}">${risky.has(a)?'△':'↻'}　${actionNames[a]}</button>`).join('')}</div><p class="hint" style="margin-top:12px">高風險操作須再次輸入確認文字。原廠重置尚未經設備驗證，不會執行未驗證指令。</p></div></section>
 <section class="panel"><div class="panel-header"><h2>Device Time</h2><small>時間設定不重啟 APP</small></div><div class="section-inner"><label class="field">自訂時間 · 本機時區 ${esc(Intl.DateTimeFormat().resolvedOptions().timeZone)} · 24 小時制<input type="datetime-local" id="device-time" step="1" min="1990-01-01T00:00:00" max="2100-12-31T23:59:59" value="${localDateValue()}" hidden><button type="button" class="time-picker-trigger" data-action="pick-device-time" aria-haspopup="dialog" aria-label="選擇裝置日期與時間"><span id="device-time-label">${UltronTimePicker.displayValue(localDateValue())}</span><span aria-hidden="true">▦</span></button></label><div class="time-row"><button class="primary" data-action="set-time">設定到選取設備</button><button data-action="sync-time">同步電腦時間</button><button data-job="network_time">恢復網路時間</button></div><div id="time-comparison">${timeComparison()}</div><p class="hint">範圍 1990–2100 年，精確至秒。真實設備需 root 權限；設定後會讀回驗證。網路校時是否完成須由裝置確認。</p></div></section></div>
 <section class="panel log-panel"><div class="panel-header"><h2>Logcat <small>LIVE LOGS</small></h2>${badge(isMock()?'模擬':'即時輪詢',isMock()?'warning':'')}</div><div class="log-controls"><select id="log-device" aria-label="Logcat 設備">${list.map(d=>`<option value="${esc(d.id)}" ${logDevice===d.id?'selected':''}>${esc(d.name)}</option>`).join('')}</select><input id="log-query" placeholder="⌕　搜尋 Logcat 內容" aria-label="搜尋 Logcat" value="${esc(logQuery)}"><select id="log-level" aria-label="Logcat 等級">${['all','V','D','I','W','E','F'].map(l=>`<option value="${l}" ${logLevel===l?'selected':''}>${l==='all'?'所有等級':l}</option>`).join('')}</select><select id="log-app" aria-label="Logcat APP 篩選"><option value="all">所有 APP</option><option value="ultron" ${logApp==='ultron'?'selected':''}>奧創 APP（PID）</option></select><button data-action="log-pause">${logPaused?'▷ 繼續捲動':'Ⅱ 暫停捲動'}</button><button data-action="log-clear">清空畫面</button><button data-action="log-export">匯出</button></div><div class="log-view" id="log-view" tabindex="0" aria-label="Logcat 記錄"></div><div class="log-footer" id="log-footer">真實模式串流全部 Logcat buffers · 前端最多保存 3,000 行</div></section></div>
 <section class="panel"><div class="panel-header"><h2>多裝置任務 <small>TASK QUEUE</small></h2><button data-action="cancel-all" class="text-button">取消目前整批任務</button></div><div id="tasks" class="task-list">${tasksMarkup()}</div></section>`;
}
function localWithOffset(value){const offset=-new Date(value).getTimezoneOffset();return value+(offset>=0?'+':'-')+String(Math.floor(Math.abs(offset)/60)).padStart(2,'0')+':'+String(Math.abs(offset)%60).padStart(2,'0');}
function localDateValue(){const d=new Date();return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,19);}
function timeComparison(){return chosen().map(d=>`<div class="status-line"><span>${esc(d.name)} · ${esc(d.deviceTime||'待驗證')}</span><span class="mono">${typeof d.timeOffset==='number'?`${d.timeOffset>=0?'+':''}${Math.round(d.timeOffset)} 秒`:'待驗證'}</span></div>`).join('')||'<p class="hint">請先選取設備</p>';}
function screenMarkup(){const ds=multiScreen?chosen():chosen().slice(0,1);return ds.map(d=>`<div class="screen" data-screen="${esc(d.id)}"><span class="screen-caption">${esc(d.name)} · ${isMock()?'模擬':'ADB'}</span>${isMock()?`<div class="mock-screen"><div class="ultron-word">ULTRON</div><p>ANDROID TV · QA PREVIEW</p><p>此為示意畫面，非裝置串流</p></div>`:`<img alt="${esc(d.name)} 即時畫面" hidden><div class="screen-message hint">等待設備畫面…</div>`}</div>`).join('')||empty('選取一台或多台設備以開始操作');}
function tasksMarkup(){return state.tasks.filter(t=>page!=='apks'||t.action==='install').slice(0,60).map(t=>`<div class="task-row"><span class="pill ${['failed','interrupted'].includes(t.status)?'bad':t.status==='succeeded'?'':'neutral'}">${esc(statusNames[t.status]||t.status)}</span><div class="task-content"><strong>${esc(state.devices.find(d=>d.id===t.device)?.name||t.device)} · ${esc(actionNames[t.action]||t.action)} ${t.mode==='mock'?'[模擬]':''}</strong><p>${esc(t.error||t.result||t.stage)}${t.backup?' · '+esc(t.backup):''}</p><div class="progress"><span style="width:${Math.max(0,Math.min(100,Number(t.progress)||0))}%"></span></div></div><div class="actions">${['queued','running','cancelling'].includes(t.status)?`<button data-cancel="${esc(t.id)}">取消單台</button><button data-cancel-batch="${esc(t.batch)}">取消整批</button>`:''}${['failed','interrupted','cancelled'].includes(t.status)?`<button data-retry="${esc(t.id)}">人工重試</button>`:''}${t.file?`<button data-download="${esc(t.file)}">另存錄影</button>`:''}<button data-task-detail="${esc(t.id)}">詳情</button></div></div>`).join('')||empty('尚無任務；操作進度與每台結果將顯示於此');}
function apksPage(){return heading('APK 版本資料庫','集中保存版本，讓每一次安裝與回復都有跡可循。',`<button data-action="drive-list">☁　列出 Google Drive</button><button class="primary" data-action="upload-focus">＋　上傳 APK</button>`)+mockNotice()+
 `<div class="apk-layout"><div><section class="panel"><div class="panel-header"><h2>版本資料庫 <small>${state.apks.length} 個版本</small></h2><span class="pill neutral">SHA-256 完整性校驗</span></div>${state.apks.map(a=>`<article class="apk-card"><div class="apk-icon">APK</div><div class="apk-info"><h3>${esc(a.filename)}</h3><div class="tag-line">${badge('v'+(a.versionName||'待驗證'))}${badge('Code '+a.versionCode,'neutral')}${a.mock?badge('模擬資料','warning'):badge(a.drive==='uploaded'?'Drive 已保存':'僅本機',a.drive==='uploaded'?'':'neutral')}</div><p class="mono" style="margin-top:10px">${esc(a.package)}</p><div class="apk-meta"><span>${fmtSize(a.size)}</span><span>上傳 ${fmtTime(a.uploaded)}</span></div><div class="hash">SHA-256　${esc(a.sha256)}</div></div><div class="apk-buttons"><button class="primary" data-install="${esc(a.id)}">安裝至設備</button><button data-drive-upload="${esc(a.id)}" ${a.mock?'disabled':''}>保存至 Drive</button></div></article>`).join('')||empty('尚無 APK，請先上傳檔案')}</section><section class="panel"><div class="panel-header"><h2>安裝與版本回復紀錄</h2><button class="text-button" data-action="history">完整歷史 ↗</button></div><div id="tasks" class="task-list">${tasksMarkup()}</div></section></div><aside><section class="panel"><div class="panel-header"><h2>上傳與保存</h2></div><div class="panel-body"><div class="dropzone"><div class="upload-symbol">↥</div><strong>新增 APK 版本</strong><p>解析 AndroidManifest、版本資訊與 SHA-256<br>單檔上限 512 MB · 先保存本機</p><input type="file" id="apk-file" accept=".apk" aria-label="上傳 APK"><p id="upload-status">選取檔案後自動上傳</p></div><div><h3>公司 Google Drive</h3><p class="hint">真實上傳由 Mac 本機服務執行。請設定公司資料夾與 OAuth token；憑證不會傳送到瀏覽器。</p><button data-action="drive-list" style="margin-top:12px">檢查資料夾與列出檔案</button></div></div></section><section class="panel"><div class="panel-header"><h2>安裝保護</h2></div><div class="panel-body"><p class="hint">01　安裝前記錄舊版，備份已安裝 APK。<br><br>02　降版需人工明確勾選，再雙重確認；Android 仍可能拒絕降版。<br><br>03　安裝後驗證版本、APP 啟動，保存異常 Logcat 供人工檢查。<br><br>04　回復請選取歷史版本再次安裝。從任務詳情下載舊版 APK，也可重新上傳；不會自動降版。<br><br>APP 私有資料不在備份範圍；split APK 的回復需人工處理。</p></div></section></aside></div>`;}
function render(){
 if(!online)return;
 $$('.nav').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('#breadcrumb').textContent=labels[page];$('#nav-count').textContent=state.devices.length;
 $('#mode-pill').textContent=isMock()?'◈ 模擬模式':'● 真實 ADB';$('#mode-pill').className='pill '+(isMock()?'warning':'');
 $('#main').innerHTML=page==='devices'?devicesPage():page==='console'?consolePage():apksPage();
 if(page==='console'){renderLogs();updateScreens();}
}
function setPage(next){if(next!==page)logController?.abort();page=next;location.hash=page;render();}
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1);if(next in labels&&next!==page){logController?.abort();page=next;render();}});
async function refreshState(full=false){if(stateBusy)return;stateBusy=true;try{
 const next=await api('/api/state');const wasOnline=online;state=next;online=true;
 selected=new Set([...selected].filter(id=>state.devices.some(d=>d.id===id)));
 if(!wasOnline&&state.devices.length&&!selected.size)selected.add(state.devices[0].id);
 $('#service-label').textContent='本機服務已連線';$('#service-dot').classList.remove('off');$('#service-url').textContent=apiBase.replace(/^https?:\/\//,'');$('#last-update').textContent='更新於 '+new Date().toLocaleTimeString('zh-TW',{hour12:false});
 if(full||!wasOnline)render();else{if($('#tasks'))$('#tasks').innerHTML=tasksMarkup();if($('#time-comparison'))$('#time-comparison').innerHTML=timeComparison();}
 }catch(e){online=false;$('#service-label').textContent='本機服務未連線';$('#service-dot').classList.add('off');$('#last-update').textContent='服務斷線 · 設備狀態未知';$('#mode-pill').textContent='服務已斷線';$('#mode-pill').className='pill bad';if(!$('#main').innerHTML||!$('#main .connection-error'))renderOffline(e.message);}finally{stateBusy=false;}}
function renderOffline(message){
 const hosted=location.origin!==apiBase;
 const pairing=hosted?`<p>這個網站只提供操作介面。請在同一台 Mac 啟動本機服務，再從本機頁面「服務設定與診斷」複製配對權杖。</p><p><a href="http://127.0.0.1:8765/" target="_blank" rel="noopener noreferrer">開啟 Mac 本機頁面 ↗</a></p><p>若瀏覽器詢問此網站存取本機網路的權限，請在確認網址後允許；若瀏覽器不支援這種連線，可直接使用本機頁面。</p>`:'';
 $('#main').innerHTML=`<div class="connection-error"><span class="pill ${hosted?'neutral':'bad'}">${hosted?'需要配對 Mac 本機服務':'本機服務未連線'}</span><h1 style="margin-top:20px">${hosted?'連接這台 Mac 的 QA 工作空間':'連接您的 QA 工作空間'}</h1><p>本機服務負責執行 ADB 與保存紀錄。請先啟動服務；模擬模式會清楚標示，真實設備操作需使用 real 模式並安裝 ADB。</p><div class="panel panel-body"><code>scripts/run-service.sh python3 mock</code></div>${pairing}<p>${esc(message)}</p><label class="field">本機 API 位址<input id="offline-api" value="${esc(apiBase)}"></label><label class="field">配對權杖（只保存在這個分頁）<input id="offline-token" type="password" autocomplete="off"></label><button class="primary" data-action="pair-offline">${hosted?'配對並連線':'重新連線'}</button></div>`;
}

async function bootstrap(){try{if(location.origin!==apiBase&&!token){online=false;renderOffline('請從本機服務取得權杖後配對；網站不會公開設備控制權。');return;}if(location.origin===apiBase){const r=await fetch(apiBase+'/api/session');if(!r.ok)throw new Error('無法取得本機 session');token=(await r.json()).token;sessionStorage.setItem('ultron-token',token);}await refreshState(true);await loadEvents();if(online)render();}catch(e){renderOffline(e.message);}}
async function runJob(action,params={},ids=[...selected]){
 if(!online)throw new Error('本機服務已斷線，禁止操作');
 if(!ids.length)throw new Error('請至少選取一台設備');
 const names=ids.map(id=>state.devices.find(d=>d.id===id)?.name||id);
 const body={action,devices:ids,params};
 if(action!=='key'){
  let extra=action==='install'?`<div class="notice">安裝前會記錄舊版與備份已安裝 APK；APP 私有資料無法備份。降版或覆寫可能造成資料損失。</div>`:action==='set_time'||action==='network_time'?'<div class="notice">設備時間將變更，APP 不會重啟。真實設備需 root，執行後讀回驗證。</div>':'';
  if(await showDialog('確認操作：'+actionNames[action],`<p>此操作將套用至以下 ${ids.length} 台設備：</p><p class="mono">${names.map(esc).join('、')}</p>${extra}${isMock()?'<p>目前為模擬模式，未對真實設備執行。</p>':''}`, [{text:'取消',value:'cancel'},{text:'確認選取與操作',value:'proceed',class:risky.has(action)?'danger':'primary'}])!=='proceed')return;
 }
 if(risky.has(action)){
  const confirm=await post('/api/confirm',body);
  const promise=showDialog('第二次確認：'+actionNames[action],`<div class="notice">${esc(confirm.warning)}</div><p>設備：${names.map(esc).join('、')}</p><label class="field">請完整輸入「${esc(confirm.phrase)}」<input id="confirm-phrase" autocomplete="off" placeholder="輸入確認文字"></label>`,[{text:'取消',value:'cancel'},{text:'執行操作',value:'execute',class:'danger'}]);
  const answer=await promise;if(answer!=='execute')return;
  body.challenge=confirm.challenge;body.phrase=$('#confirm-phrase').value;
 }
 const result=await post('/api/tasks',body);toast(`已建立 ${result.length} 台設備任務${isMock()?'（模擬）':''}`);await refreshState();
}
async function detail(id){const d=state.devices.find(d=>d.id===id);if(!d)return;
 const fields=[['VersionCode',d.versionCode],['VersionName',d.versionName],['Set-Up Box',d.box],['硬體品牌',d.hardware],['Local IP',d.localIP],['Public IP',d.publicIP],['Device Time',d.deviceTime],['DeviceID',d.deviceID],['ADB',d.adb],['奧創 APP',d.app],['網路',d.network],['最後連線',fmtTime(d.lastSeen)]];
 const result=await showDialog('裝置詳細資訊',`<div class="form-grid"><label class="field">裝置名稱<input id="edit-name" value="${esc(d.name)}" maxlength="80"></label><label class="field">品牌<input id="edit-brand" value="${esc(d.brand||'')}" maxlength="80"></label><label class="field">店家<input id="edit-store" value="${esc(d.store||'')}" maxlength="80"></label><label class="check-row"><input type="checkbox" id="edit-reconnect" ${d.autoReconnect!==false?'checked':''}>斷線後每 10 秒嘗試重連</label></div><div class="device-details">${fields.map(([k,v])=>`<div class="detail-field"><small>${k}</small><span>${esc(v)}</span></div>`).join('')}</div>${d.error?`<p>${esc(d.error)}</p>`:''}`, [{text:'關閉',value:'cancel'},{text:'儲存裝置資料',value:'save',class:'primary'}]);
 if(result==='save'){const body={id,name:$('#edit-name').value,autoReconnect:$('#edit-reconnect').checked};if($('#edit-brand').value.trim())body.brand=$('#edit-brand').value;if($('#edit-store').value.trim())body.store=$('#edit-store').value;await post('/api/device',body);toast('裝置資料已儲存');await refreshState(true);}
}
function renderLogs(){const el=$('#log-view');if(!el)return;const visible=logLines.filter(l=>(logLevel==='all'||l.level===logLevel)&&(logApp==='all'||l.package===state.package)&&l.text.toLowerCase().includes(logQuery.toLowerCase()));const top=el.scrollTop;el.innerHTML=visible.map(l=>`<div class="log-line" data-level="${esc(l.level)}">${esc(l.text)}</div>`).join('')||'<span class="muted">等待 Logcat，或目前沒有符合篩選的紀錄。</span>';if(!logPaused)el.scrollTop=el.scrollHeight;else el.scrollTop=top;$('#log-footer').textContent=`顯示 ${visible.length} / ${logLines.length} 行 · ${isMock()?'每 2 秒模擬更新':'ADB 即時串流 · 全部 buffers'} · ${logPaused?'捲動已暫停':'自動捲動'}`;}
async function pollLogs(){if(page!=='console'||!online||!logDevice||logBusy)return;if(!isMock())return liveLogs();logBusy=true;try{const id=logDevice;const lines=await api('/api/logs?device='+encodeURIComponent(id));if(id!==logDevice)return;for(const line of lines)if(!logIds.has(line.id)){logIds.add(line.id);logLines.push(line);}if(logLines.length>3000){logLines=logLines.slice(-3000);logIds=new Set(logLines.map(l=>l.id));}renderLogs();}catch(e){if($('#log-footer'))$('#log-footer').textContent='Logcat 未取得：'+e.message;}finally{logBusy=false;}}

async function liveLogs(){
 if(logBusy)return;logBusy=true;logController=new AbortController();const id=logDevice;
 let updateAt=0;
 try{
  const response=await fetch(apiBase+'/api/logs/stream?device='+encodeURIComponent(id),{headers:{'X-Ultron-Token':token},signal:logController.signal});
  if(!response.ok)throw new Error((await response.json()).error||'Logcat 連線失敗');
  const reader=response.body.getReader();const decoder=new TextDecoder();let pending='';
  while(page==='console'&&id===logDevice&&online){
   const {value,done}=await reader.read();if(done)break;
   pending+=decoder.decode(value,{stream:true});
   let newline;
   while((newline=pending.indexOf('\n'))>=0){
    const data=JSON.parse(pending.slice(0,newline));pending=pending.slice(newline+1);
    if(data.error)throw new Error(data.error);
    if(data.id&&!logIds.has(data.id)){logIds.add(data.id);logLines.push(data);}
   }
   if(logLines.length>3000){logLines=logLines.slice(-3000);logIds=new Set(logLines.map(l=>l.id));}
   if(Date.now()-updateAt>200){renderLogs();updateAt=Date.now();}
  }
  await reader.cancel();renderLogs();
 }catch(e){if(e.name!=='AbortError'&&$('#log-footer'))$('#log-footer').textContent='Logcat 串流中斷：'+e.message+'（自動重連）';}
 finally{logBusy=false;}
}

async function updateScreens(){if(page!=='console'||!online||isMock()||!screenStreaming||screenBusy)return;screenBusy=true;try{
 await Promise.all($$('[data-screen]').map(async el=>{try{const r=await api('/api/screen?device='+encodeURIComponent(el.dataset.screen),{blob:true});if(!el.isConnected)return;const id=el.dataset.screen;const old=screenURLs.get(id);const u=URL.createObjectURL(r.blob);screenURLs.set(id,u);const img=$('img',el);img.src=u;img.hidden=false;$('.screen-message',el).hidden=true;if(old)URL.revokeObjectURL(old);}catch(e){if(el.isConnected){$('.screen-message',el).textContent=e.message;$('.screen-message',el).hidden=false;$('img',el).hidden=true;}}}));
 }finally{screenBusy=false;}}
const screenshotFiles = new Map();
async function captureScreenshots(){
 if(!online)throw new Error('本機服務已斷線，無法擷取畫面');
 const devices=chosen().map(d=>({...d}));
 const results=await UltronScreenshots.captureAll({devices,mock:isMock(),fetchScreenshot:id=>api('/api/screenshot?device='+encodeURIComponent(id),{blob:true}),onProgress:(d,i,total)=>toast(`正在擷取 ${d.name}（${i+1}/${total}）…`)});
 const urls=[];
 try{
  const html=results.map((r,index)=>{
   if(r.error)return `<section class="screenshot-result"><h3>${esc(r.device.name)}</h3><p class="screenshot-error">截圖失敗：${esc(r.error)}</p></section>`;
   const url=URL.createObjectURL(r.blob);urls.push(url);screenshotFiles.set(url,r);
   return `<section class="screenshot-result"><h3>${esc(r.device.name)} ${r.mock?badge('模擬預覽','warning'):badge('ADB 截圖')}</h3><img class="screenshot-preview" src="${url}" alt="${esc(r.device.name)} ${r.mock?'模擬預覽，非真實設備畫面':'設備截圖'}"><p class="mono">${esc(r.name)}</p><div class="actions"><a class="screenshot-download" href="${url}" download="${esc(r.name)}">下載 PNG</a>${typeof window.showSaveFilePicker==='function'?`<button data-save-screenshot="${url}">選擇位置另存…</button>`:''}</div><p class="hint">${r.mock?'此檔案為清楚標示的模擬預覽，未呼叫 ADB，未保存為真實設備截圖。':'原圖已保存在 Mac 本機服務，可再下載到指定位置。'}若下載未啟動，可在預覽圖片上按右鍵另存圖片。</p></section>`;
  }).join('');
  const successes=results.filter(r=>!r.error).length;
  toast(`擷取完成：${successes}/${results.length} 台，請在預覽中選擇下載`,successes===0);
  await showDialog(`截圖另存 · ${successes}/${results.length} 台`,html);
 }finally{for(const url of urls){screenshotFiles.delete(url);URL.revokeObjectURL(url);}}
}
async function saveScreenshotToFile(url){
 const file=screenshotFiles.get(url);if(!file)throw new Error('截圖預覽已關閉，請重新擷取');
 try{
  const handle=await window.showSaveFilePicker({suggestedName:file.name,types:[{description:'PNG 圖片',accept:{'image/png':['.png']}}]});
  const stream=await handle.createWritable();
  try{await stream.write(file.blob);await stream.close();}catch(error){try{await stream.abort();}catch{}throw error;}
  toast('PNG 已另存至選取位置');
 }catch(error){if(error.name!=='AbortError')throw error;}
}

async function history(){await loadEvents();showDialog('操作、異常與稽核紀錄',`<div class="actions" style="margin-bottom:18px"><button data-action="export-csv">匯出 CSV</button><small>最多顯示最近 2,000 筆 · 時間為本機顯示</small></div>${events.map(e=>`<div class="event-line"><span class="event-dot ${e.kind.includes('fail')||e.kind==='alert'?'bad':''}"></span><div><strong>${esc(eventLabel(e.kind))}</strong><small class="sub">${esc(fmtTime(e.at))} · ${esc(e.device)} · IP ${esc(e.ip)} · Session ${esc(e.session)}</small><p class="mono" style="white-space:pre-wrap;overflow-wrap:anywhere;margin-top:6px">${esc(e.detail)}</p></div></div>`).join('')||empty('尚無紀錄')}`);}
async function settings(){let diag;try{diag=await api('/api/diagnostics');}catch(e){diag={error:e.message};}
 const result=await showDialog('本機服務設定與系統診斷',`<label class="field">API 位址（僅接受本機 HTTP）<input id="settings-api" value="${esc(apiBase)}"></label><label class="field">本機配對權杖<input type="password" id="settings-token" value="${esc(token)}" autocomplete="off"></label><div class="actions" style="margin-bottom:20px"><button data-action="copy-token">複製權杖</button><button data-action="backup">手動備份 SQLite</button><button data-action="restore-select" class="danger">還原資料庫</button><input type="file" id="restore-file" accept=".sqlite3,.db" hidden></div><p>備份僅包含 SQLite；APK 與錄影位於 .runtime/apks、.runtime/media，請另外保存。管理 Mac 登入自動啟動及停止，請使用 scripts/service.sh。</p><pre>${esc(JSON.stringify(diag,null,2))}</pre>`,[{text:'關閉',value:'cancel'},{text:'儲存並連線',value:'save',class:'primary'}]);
 if(result==='save')await pair($('#settings-api').value,$('#settings-token').value);
}
async function pair(base,value){const u=new URL(base);if(u.protocol!=='http:'||!['127.0.0.1','localhost'].includes(u.hostname)||u.username||u.password||u.pathname!=='/'||u.search||u.hash)throw new Error('僅允許 http://127.0.0.1:埠號 或 localhost 本機 API');apiBase=u.origin;token=value.trim();localStorage.setItem('ultron-api',apiBase);sessionStorage.setItem('ultron-token',token);await bootstrap();}
async function install(id){const apk=state.apks.find(a=>a.id===id);const r=await showDialog('選擇 APK 安裝設備',`<p><strong>${esc(apk.filename)}</strong><br>${esc(apk.package)} · Code ${esc(apk.versionCode)}</p><div>${state.devices.map(d=>`<label class="check-row"><input type="checkbox" data-install-device="${esc(d.id)}" ${selected.has(d.id)?'checked':''} ${connected(d)?'':'disabled'}>${esc(d.name)} · ${esc(d.id)} · 目前 Code ${esc(d.versionCode)}</label>`).join('')}</div><label class="check-row"><input id="allow-downgrade" type="checkbox">明確允許手動降版／版本回復（可能失敗或遺失資料）</label><p>不會自動降版。已安裝的舊版 APK 會先備份，APP 私有資料不包含在內。</p>`,[{text:'取消',value:'cancel'},{text:'檢查安裝條件',value:'install',class:'primary'}]);if(r==='install'){const ids=$$('[data-install-device]:checked').map(el=>el.dataset.installDevice);const allow=$('#allow-downgrade').checked;await runJob('install',{apk:id,allowDowngrade:allow},ids);}}
const handlers={
 'connect':async()=>{const result=await showDialog('手動連線 ADB 裝置','<p>設備須開啟網路 ADB 並授權此 Mac。Android 配對碼流程請先使用 adb pair；此處提供傳統 TCP/IP 連線。</p><label class="field">LAN IP : Port<input id="connect-ip" placeholder="192.168.1.101:5555" autocomplete="off"></label>',[{text:'取消',value:'cancel'},{text:'連線',value:'connect',class:'primary'}]);if(result==='connect'){await post('/api/connect',{ip:$('#connect-ip').value});await refreshState(true);toast(isMock()?'模擬裝置已新增':'ADB 連線完成');}},
 'discover':async()=>{const r=await showDialog('搜尋區域網路','<p>僅搜尋您指定的私人 /24 或更小網段，探測 TCP 5555。設備必須已開啟網路 ADB；其他埠號請使用手動連線。</p><label class="field">LAN 網段<input id="scan-cidr" value="192.168.1.0/24"></label>',[{text:'取消',value:'cancel'},{text:'搜尋並連線',value:'scan',class:'primary'}]);if(r==='scan'){toast('正在搜尋區域網路…');const found=await post('/api/discover',{cidr:$('#scan-cidr').value});await refreshState(true);toast(`搜尋完成：${found.length} 台${isMock()?'（模擬）':''}`);}},
 'refresh':async()=>{await post('/api/refresh');await loadEvents();await refreshState(true);toast('已手動刷新');},
 'open-console':()=>setPage('console'),
 'select-connected':()=>{selected=new Set(state.devices.filter(connected).map(d=>d.id));render();},
 'history':history,'settings':settings,
 'screen-toggle':()=>{screenStreaming=!screenStreaming;render();},
 'multi-screen':()=>{multiScreen=!multiScreen;render();},
 'screenshot':captureScreenshots,
 'fullscreen':async()=>{const el=$('#screen-grid');if(!el?.requestFullscreen)throw new Error('此瀏覽器不支援全螢幕');await el.requestFullscreen();},
 'pick-device-time':async()=>{const value=await UltronTimePicker.open($('#device-time').value);if(value&&$('#device-time')){$('#device-time').value=value;$('#device-time-label').textContent=UltronTimePicker.displayValue(value);}},
 'set-time':async()=>{const val=$('#device-time');if(!val.reportValidity()||!val.value)throw new Error('請輸入有效的 1990～2100 年日期時間');await runJob('set_time',{time:localWithOffset(val.value)});},
 'sync-time':async()=>runJob('set_time',{syncComputer:true}),
 'log-pause':()=>{logPaused=!logPaused;const b=$('[data-action="log-pause"]');b.textContent=logPaused?'▷ 繼續捲動':'Ⅱ 暫停捲動';renderLogs();},
 'log-clear':()=>{logLines=[];if(logIds.size>6000)logIds=new Set([...logIds].slice(-3000));/* Keep seen IDs so clearing the display does not replay the device buffer. */renderLogs();},
 'log-export':()=>{const lines=logLines.filter(l=>(logLevel==='all'||l.level===logLevel)&&(logApp==='all'||l.package===state.package)&&l.text.toLowerCase().includes(logQuery.toLowerCase()));saveBlob(new Blob([lines.map(l=>l.text).join('\n')],{type:'text/plain;charset=utf-8'}),'ultron-logcat-'+new Date().toISOString().replace(/[:.]/g,'-')+'.txt');},
 'cancel-all':async()=>{const batches=[...new Set(state.tasks.filter(t=>['queued','running','cancelling'].includes(t.status)).map(t=>t.batch))];for(const id of batches)await post('/api/cancel',{id,batch:true});toast('已要求取消所有未完成批次；已送出變更無法撤回');await refreshState();},
 'upload-focus':()=>$('#apk-file').click(),
 'drive-list':async()=>{const r=await api('/api/drive');showDialog('公司 Google Drive APK',`<p>列出設定資料夾內的 APK。可將公司資料夾內的 APK 下載至本機，重新解析 Manifest 與 SHA-256 後，再選擇設備安裝。</p>${(r.files||[]).filter(f=>f.name.toLowerCase().endsWith('.apk')).map(f=>`<div class="detail-field"><strong>${esc(f.name)}</strong><p class="mono">${esc(JSON.stringify(f.appProperties||{}))}</p><small>${fmtSize(Number(f.size||0))} · ${fmtTime(f.createdTime)} · ${esc(f.id)}</small><button data-drive-download="${esc(f.id)}" style="margin-top:10px">下載至本機版本庫</button></div>`).join('')||empty('資料夾內沒有 APK')}${r.nextPageToken?'<p>資料超過 1,000 筆，後續分頁尚未載入。</p>':''}`);},
 'backup':()=>download('/api/backup','ultron-backup.sqlite3'),
 'export-csv':()=>download('/api/export','ultron-events.csv'),
 'restore-select':()=>$('#restore-file').click(),
 'copy-token':async()=>{await navigator.clipboard.writeText(token);toast('配對權杖已複製；請只提供給您信任的前端');},
 'pair-offline':()=>pair($('#offline-api').value,$('#offline-token').value)
};
document.addEventListener('click',async e=>{const button=e.target.closest('button');if(!button)return;try{
 if(button.dataset.page){setPage(button.dataset.page);return;}
 if(button.dataset.action){const action=button.dataset.action;if(handlers[action]){button.disabled=true;try{await handlers[action]();}finally{button.disabled=false;}}return;}
 if(button.dataset.key){await runJob('key',{key:button.dataset.key});return;}
 if(button.dataset.job){await runJob(button.dataset.job);return;}
 if(button.dataset.chip){logController?.abort();const id=button.dataset.chip;selected.has(id)?selected.delete(id):selected.add(id);logLines=[];logIds.clear();render();return;}
 if(button.dataset.detail){await detail(button.dataset.detail);return;}
 if(button.dataset.cancel||button.dataset.cancelBatch){await post('/api/cancel',{id:button.dataset.cancel||button.dataset.cancelBatch,batch:!!button.dataset.cancelBatch});await refreshState();return;}
 if(button.dataset.retry){const task=state.tasks.find(t=>t.id===button.dataset.retry);if(task.mode!==state.mode)throw new Error('任務模式與目前服務不符，請重新選取設備操作');await runJob(task.action,task.params,[task.device]);return;}
 if(button.dataset.saveScreenshot){await saveScreenshotToFile(button.dataset.saveScreenshot);return;}
 if(button.dataset.download){await download('/api/file?name='+encodeURIComponent(button.dataset.download),button.dataset.download);return;}
 if(button.dataset.install){await install(button.dataset.install);return;}
 if(button.dataset.driveDownload){button.disabled=true;try{await post('/api/drive/download',{id:button.dataset.driveDownload});closeDialog('downloaded');await refreshState(true);toast('已從 Drive 下載並完成本機 APK 解析');}finally{button.disabled=false;}return;}
 if(button.dataset.driveUpload){button.disabled=true;try{await post('/api/drive/upload',{id:button.dataset.driveUpload});await refreshState(true);toast('Google Drive 已回覆上傳成功');}finally{button.disabled=false;}return;}
 if(button.dataset.taskDetail){const t=state.tasks.find(t=>t.id===button.dataset.taskDetail);showDialog('任務詳情',`<pre>${esc(JSON.stringify(t,null,2))}</pre><div class="actions">${(t.backupFiles||[]).map(f=>`<button data-download="${esc(f)}">下載舊版 ${esc(f)}</button>`).join('')}</div>`);}
 }catch(err){toast(err.message,true);}});
document.addEventListener('change',async e=>{const el=e.target;try{
 if(el.dataset.select){el.checked?selected.add(el.dataset.select):selected.delete(el.dataset.select);render();}
 if(el.id==='select-all'){selected=el.checked?new Set(state.devices.map(d=>d.id)):new Set();render();}
 if(el.id==='device-status'){deviceStatus=el.value;render();}
 if(el.id==='auto-refresh')localStorage.setItem('ultron-auto',el.checked?'on':'off');
 if(el.id==='log-device'){logController?.abort();logDevice=el.value;logLines=[];logIds.clear();renderLogs();pollLogs();}
 if(el.id==='log-level'){logLevel=el.value;renderLogs();}
 if(el.id==='log-app'){logApp=el.value;renderLogs();}
 if(el.id==='apk-file'&&el.files[0]){const file=el.files[0];if(file.size>512*1024*1024)throw new Error('APK 超過 512 MB 限制');$('#upload-status').textContent='正在上傳與解析 APK…';await api('/api/apks/upload',{method:'POST',raw:file,filename:file.name});await refreshState(true);toast('APK 已保存本機並解析版本與 SHA-256；尚未上傳 Drive');}
 if(el.id==='restore-file'&&el.files[0]){const file=el.files[0];if(await showDialog('還原 SQLite 資料庫','<div class="notice">將取代目前的裝置、任務、版本與操作紀錄。服務會先保存還原前備份；APK 及媒體檔案不包含在 SQLite 備份內。</div>',[{text:'取消',value:'cancel'},{text:'繼續還原確認',value:'next',class:'danger'}])!=='next')return;const c=await post('/api/restore/confirm');if(await showDialog('第二次確認：資料還原',`<label class="field">請輸入「${esc(c.phrase)}」<input id="restore-phrase" autocomplete="off"></label>`,[{text:'取消',value:'cancel'},{text:'執行還原',value:'restore',class:'danger'}])!=='restore')return;await api('/api/restore?challenge='+encodeURIComponent(c.challenge)+'&phrase='+encodeURIComponent($('#restore-phrase').value),{method:'POST',raw:file});await refreshState(true);toast('資料庫已還原；未自動重送中斷任務');}
 }catch(err){toast(err.message,true);if($('#upload-status'))$('#upload-status').textContent=err.message;}});
document.addEventListener('input',e=>{if(e.target.id==='device-search'){const pos=e.target.selectionStart;deviceSearch=e.target.value;render();$('#device-search').focus();$('#device-search').setSelectionRange(pos,pos);}if(e.target.id==='log-query'){logQuery=e.target.value;renderLogs();}});
let lastKeyTime=0;
document.addEventListener('keydown',async e=>{if(page!=='console'||document.querySelector('dialog[open]')||e.target.closest('input,select,textarea,[contenteditable="true"],button')||e.metaKey||e.ctrlKey||e.altKey||!online)return;const keys={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Enter:'ok',Escape:'back',h:'home',H:'home',s:'source',S:'source','+':'volume_up','=':'volume_up','-':'volume_down'};const key=keys[e.key]||(/^\d$/.test(e.key)?e.key:null);if(!key)return;e.preventDefault();if(Date.now()-lastKeyTime<120)return;lastKeyTime=Date.now();try{await runJob('key',{key});}catch(err){toast(err.message,true);}});
$('#theme-toggle').addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=next;localStorage.setItem('ultron-theme',next);});
document.documentElement.dataset.theme=localStorage.getItem('ultron-theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
setInterval(()=>{if(online)refreshState();},2000);
setInterval(async()=>{if(!online)return;if(localStorage.getItem('ultron-auto')!=='off'){await loadEvents();if(page==='devices'&&!$('#dialog').open&&!document.activeElement?.closest('input,select'))refreshState(true);}},10000);
setInterval(pollLogs,2000);setInterval(updateScreens,1500);
bootstrap();
