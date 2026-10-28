/* Screenshot export: mock previews are visibly labelled, real images come only from ADB. */
(function (root) {
  'use strict';
  const signature = [137,80,78,71,13,10,26,10];
  function filename(device, mock, date = new Date()) {
    const name = String(device.name || device.id || 'device').replace(/[^\p{L}\p{N}_-]/gu,'_').slice(0,60);
    const stamp = date.toISOString().replace(/[-:]/g,'').replace('T','_').replace(/\.\d+Z$/,'Z');
    return `${name}_${mock?'MOCK_preview':'screenshot'}_${stamp}.png`;
  }
  function responseFilename(disposition, fallback) {
    const match = disposition?.match(/filename\*=UTF-8''([^;]+)/i);
    if (!match) return fallback;
    try {
      const value = decodeURIComponent(match[1]).replace(/[/\\\x00-\x1f]/g,'_');
      return value.toLowerCase().endsWith('.png') ? value : fallback;
    } catch { return fallback; }
  }
  async function validatePNG(blob) {
    const bytes = new Uint8Array(await blob.slice(0,8).arrayBuffer());
    if (bytes.length !== signature.length || !signature.every((b,i)=>bytes[i]===b)) throw new Error('設備未回傳有效 PNG，未產生截圖');
  }
  async function mockPreview(device) {
    const canvas = document.createElement('canvas');
    canvas.width = 1280; canvas.height = 720;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('此瀏覽器無法匯出模擬預覽圖片');
    ctx.fillStyle = '#0b131b';ctx.fillRect(0,0,1280,720);
    ctx.textAlign = 'center';ctx.textBaseline = 'middle';
    ctx.fillStyle = '#75d0b6';ctx.font = 'bold 72px sans-serif';ctx.fillText('ULTRON',640,320);
    ctx.fillStyle = '#8b9aaa';ctx.font = '24px sans-serif';ctx.fillText('ANDROID TV · QA PREVIEW',640,395);
    ctx.fillText('此為示意畫面，非裝置串流',640,447);
    ctx.fillStyle = '#20312f';ctx.fillRect(0,0,1280,76);
    ctx.fillStyle = '#e9bb67';ctx.font = 'bold 27px sans-serif';ctx.fillText('模擬預覽 · 非真實設備截圖 / MOCK PREVIEW',640,38);
    ctx.fillStyle = '#8b9aaa';ctx.font = '20px sans-serif';
    ctx.fillText(String(device.name || device.id).slice(0,70)+' · '+new Date().toLocaleString('zh-TW',{hour12:false}),640,661,1200);
    return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('模擬預覽 PNG 匯出失敗')),'image/png'));
  }
  async function captureAll({devices,mock,fetchScreenshot,makeMockBlob=mockPreview,onProgress=()=>{}}) {
    if (!devices.length) throw new Error('請先選取至少一台設備');
    const results = [];
    for (const device of devices) {
      onProgress(device,results.length,devices.length);
      try {
        if (!mock && device.adb!=='connected') throw new Error('設備已離線，無法擷取畫面');
        const response = mock ? {blob:await makeMockBlob(device)} : await fetchScreenshot(device.id);
        await validatePNG(response.blob);
        const fallback=filename(device,mock);
        results.push({device,mock,blob:response.blob,name:mock?fallback:responseFilename(response.disposition,fallback)});
      } catch (error) {
        results.push({device,mock,error:error.message || String(error)});
      }
    }
    return results;
  }
  const api={captureAll,filename,responseFilename,validatePNG};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  else root.UltronScreenshots=api;
})(typeof window!=='undefined'?window:this);
