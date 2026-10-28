/* Local calendar and bounded 24-hour time wheels. No device operation is performed here. */
(function (root) {
  'use strict';
  const pad = n => String(n).padStart(2, '0');
  const ranges = Object.freeze({hour: [1, 24], minute: [0, 59], second: [0, 59]});
  function clampUnit(unit, value) {
    const [min, max] = ranges[unit];
    return Math.max(min, Math.min(max, Math.round(value)));
  }
  function parseValue(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/.exec(value);
    if (!match) throw new Error('日期時間格式無效');
    const [, y, m, d, h, min, sec] = match.map(Number);
    const days = new Date(y, m, 0).getDate();
    if (y < 1990 || y > 2100 || m < 1 || m > 12 || d < 1 || d > days || h > 23 || min > 59 || sec > 59) {
      throw new Error('日期時間超出允許範圍');
    }
    return {year: y, month: m, day: d, hour: h === 0 ? 24 : h, minute: min, second: sec};
  }
  function formatValue(parts) {
    // h24 convention: 24 represents the selected date's midnight (00), not the next date.
    const value = `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour === 24 ? 0 : parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}`;
    parseValue(value);
    if (parts.hour < 1 || parts.hour > 24) throw new Error('時必須介於 1～24');
    return value;
  }
  function displayValue(value) {
    const p = parseValue(value);
    return `${p.year}/${pad(p.month)}/${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
  }
  function open(value) {
    const parts = parseValue(value);
    let viewYear = parts.year, viewMonth = parts.month;
    const dialog = document.createElement('dialog');
    dialog.className = 'device-time-picker';
    dialog.setAttribute('aria-label', '選擇裝置日期與時間');
    dialog.innerHTML = `<div class="dialog-head"><h2>選擇日期與時間</h2><button type="button" class="icon-button" data-picker-close aria-label="關閉日期時間選擇器">×</button></div>
      <div class="date-time-picker-body"><section class="picker-calendar" aria-label="行事曆"><div class="calendar-toolbar"><button type="button" data-month-step="-1" aria-label="上個月">‹</button><select aria-label="年份" id="picker-year">${Array.from({length:111},(_,i)=>`<option value="${1990+i}">${1990+i} 年</option>`).join('')}</select><select aria-label="月份" id="picker-month">${Array.from({length:12},(_,i)=>`<option value="${i+1}">${i+1} 月</option>`).join('')}</select><button type="button" data-month-step="1" aria-label="下個月">›</button></div><div class="calendar-weekdays">${['日','一','二','三','四','五','六'].map(d=>`<span>${d}</span>`).join('')}</div><div class="calendar-days" role="group" aria-label="日期"></div></section>
      <section class="picker-time" aria-label="24 小時制時間"><div class="time-wheel-headers"><span>時</span><span>分</span><span>秒</span></div><div class="time-wheels">${Object.entries(ranges).map(([unit,[min,max]])=>`<div class="time-wheel" tabindex="0" role="listbox" aria-label="${{hour:'時',minute:'分',second:'秒'}[unit]}" data-unit="${unit}">${Array.from({length:max-min+1},(_,i)=>`<button type="button" tabindex="-1" role="option" aria-selected="false" data-unit-value="${i+min}">${pad(i+min)}</button>`).join('')}</div>`).join('')}</div></section></div>
      <div class="picker-selection" aria-live="polite"></div><div class="dialog-footer"><button type="button" data-picker-close>取消</button><button type="button" class="primary" data-picker-save>確定</button></div>`;
    document.body.append(dialog);
    const yearSelect = dialog.querySelector('#picker-year');
    const monthSelect = dialog.querySelector('#picker-month');
    const calendar = dialog.querySelector('.calendar-days');
    const wheels = [...dialog.querySelectorAll('.time-wheel')];
    const updateSummary = () => {dialog.querySelector('.picker-selection').textContent = displayValue(formatValue(parts));};
    function renderCalendar() {
      yearSelect.value = viewYear;
      monthSelect.value = viewMonth;
      const firstDay = new Date(viewYear, viewMonth - 1, 1).getDay();
      const days = new Date(viewYear, viewMonth, 0).getDate();
      calendar.innerHTML = '<span></span>'.repeat(firstDay) + Array.from({length:days},(_,i)=>{
        const day = i+1;
        const selected = viewYear===parts.year && viewMonth===parts.month && day===parts.day;
        return `<button type="button" data-calendar-day="${day}" aria-label="${viewYear}年${viewMonth}月${day}日" aria-pressed="${selected}">${day}</button>`;
      }).join('');
      dialog.querySelector('[data-month-step="-1"]').disabled = viewYear===1990 && viewMonth===1;
      dialog.querySelector('[data-month-step="1"]').disabled = viewYear===2100 && viewMonth===12;
    }
    function updateWheel(wheel, number) {
      const unit = wheel.dataset.unit;
      parts[unit] = clampUnit(unit,number);
      for (const option of wheel.children) option.setAttribute('aria-selected', String(Number(option.dataset.unitValue)===parts[unit]));
      wheel.setAttribute('aria-activedescendant', `picker-${unit}-${parts[unit]}`);
      updateSummary();
    }
    function scrollToValue(wheel, number, smooth=false) {
      updateWheel(wheel,number);
      wheel.scrollTo({top:(parts[wheel.dataset.unit]-ranges[wheel.dataset.unit][0])*32,behavior:smooth?'smooth':'instant'});
    }
    renderCalendar();
    updateSummary();
    dialog.showModal();
    for (const wheel of wheels) {
      for (const option of wheel.children) option.id = `picker-${wheel.dataset.unit}-${option.dataset.unitValue}`;
      scrollToValue(wheel,parts[wheel.dataset.unit]);
      wheel.addEventListener('scroll',()=>updateWheel(wheel,ranges[wheel.dataset.unit][0]+Math.round(wheel.scrollTop/32)),{passive:true});
      wheel.addEventListener('keydown',e=>{
        const key = e.key, unit = wheel.dataset.unit;
        const next = {ArrowDown:parts[unit]+1,ArrowUp:parts[unit]-1,PageDown:parts[unit]+10,PageUp:parts[unit]-10,Home:ranges[unit][0],End:ranges[unit][1]}[key];
        if (next!==undefined) {e.preventDefault();scrollToValue(wheel,next);}
      });
    }
    return new Promise(resolve=>{
      let result = null;
      dialog.addEventListener('close',()=>{dialog.remove();resolve(result);},{once:true});
      dialog.addEventListener('click',e=>{
        if(e.target.closest('[data-picker-close]')) dialog.close();
        if(e.target.closest('[data-picker-save]')) {result=formatValue(parts);dialog.close();}
        const option=e.target.closest('[data-unit-value]');
        if(option) scrollToValue(option.closest('.time-wheel'),Number(option.dataset.unitValue),true);
        const day=e.target.closest('[data-calendar-day]');
        if(day) {Object.assign(parts,{year:viewYear,month:viewMonth,day:Number(day.dataset.calendarDay)});renderCalendar();updateSummary();}
        const step=e.target.closest('[data-month-step]');
        if(step) {const next=new Date(viewYear,viewMonth-1+Number(step.dataset.monthStep),1);viewYear=next.getFullYear();viewMonth=next.getMonth()+1;renderCalendar();}
      });
      yearSelect.addEventListener('change',()=>{viewYear=Number(yearSelect.value);renderCalendar();});
      monthSelect.addEventListener('change',()=>{viewMonth=Number(monthSelect.value);renderCalendar();});
    });
  }
  const api = {open,parseValue,formatValue,displayValue,clampUnit,ranges};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.UltronTimePicker = api;
})(typeof window !== 'undefined' ? window : this);
