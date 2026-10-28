const {test} = require('node:test');
const assert = require('node:assert/strict');
const screenshots = require('../web/screenshots.js');
const png = new Blob([Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1kAAAAASUVORK5CYII=','base64')],{type:'image/png'});
const device = {id:'192.168.1.101:5555',name:'STB101',adb:'connected'};

test('模擬截圖能產生 PNG 且強制帶模擬水印、檔名，不呼叫真實 ADB API',async()=>{
 const texts=[];let apiCalls=0;
 const original=global.document;
 global.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(text){texts.push(text);}}),toBlob:callback=>callback(png)})};
 try{
  const result=await screenshots.captureAll({devices:[device],mock:true,fetchScreenshot:()=>{apiCalls++;throw new Error('must not call');}});
  assert.equal(apiCalls,0);
  assert.equal(result[0].blob,png);
  assert.match(result[0].name,/_MOCK_preview_/);
  assert.ok(texts.some(t=>t.includes('非真實設備截圖')&&t.includes('MOCK PREVIEW')));
 }finally{global.document=original;}
});
test('真實模式使用設備 API 並保留伺服器自動檔名',async()=>{
 const ids=[];
 const result=await screenshots.captureAll({devices:[device],mock:false,fetchScreenshot:async id=>{ids.push(id);return {blob:png,disposition:"attachment; filename*=UTF-8''STB101_screenshot.png"};}});
 assert.deepEqual(ids,[device.id]);assert.equal(result[0].name,'STB101_screenshot.png');assert.equal(result[0].mock,false);
});
test('單台失敗不會阻止其他已選取設備截圖',async()=>{
 const second={...device,id:'192.168.1.102:5555',name:'STB102'};
 const result=await screenshots.captureAll({devices:[device,second],mock:false,fetchScreenshot:async id=>{if(id===device.id)throw new Error('ADB 逾時');return {blob:png};}});
 assert.equal(result[0].error,'ADB 逾時');assert.equal(result[1].blob,png);
});
test('離線設備不發出請求；未選設備會顯示錯誤',async()=>{
 let calls=0;
 const result=await screenshots.captureAll({devices:[{...device,adb:'disconnected'}],mock:false,fetchScreenshot:()=>{calls++;}});
 assert.equal(calls,0);assert.match(result[0].error,/離線/);
 await assert.rejects(()=>screenshots.captureAll({devices:[],mock:true}),/選取/);
});
test('無效回應不會匯出成 PNG，也不宣稱擷取成功',async()=>{
 const result=await screenshots.captureAll({devices:[device],mock:false,fetchScreenshot:async()=>({blob:new Blob(['not PNG'])})});
 assert.match(result[0].error,/有效 PNG/);assert.equal(result[0].blob,undefined);
});
test('檔名安全與錯誤 Content-Disposition 回復預設檔名',()=>{
 assert.equal(screenshots.filename({...device,name:'STB/../測試'},true,new Date('2026-10-27T10:00:00Z')),'STB____測試_MOCK_preview_20261027_100000Z.png');
 assert.equal(screenshots.responseFilename("attachment; filename*=UTF-8''%E0%A4",'fallback.png'),'fallback.png');
 assert.equal(screenshots.responseFilename("attachment; filename*=UTF-8''wrong.html",'fallback.png'),'fallback.png');
});
