const {test} = require('node:test');
const assert = require('node:assert/strict');
const picker = require('../web/time-picker.js');

test('午夜顯示 24，送至設備仍為選定日期的 00 時，不會換日', () => {
  const p = picker.parseValue('2026-10-27T00:59:59');
  assert.equal(p.hour, 24);
  assert.equal(picker.formatValue(p), '2026-10-27T00:59:59');
  assert.equal(picker.displayValue('2026-10-27T00:59:59'), '2026/10/27 24:59:59');
});
test('下午維持 24 小時數值，沒有上午下午標記', () => {
  assert.equal(picker.displayValue('2026-10-27T13:05:09'), '2026/10/27 13:05:09');
});
test('時欄在 1 和 24 停止，分秒在 0 和 59 停止，不循環', () => {
  assert.equal(picker.clampUnit('hour', 25), 24);
  assert.equal(picker.clampUnit('hour', 0), 1);
  for (const unit of ['minute', 'second']) {
    assert.equal(picker.clampUnit(unit, 60), 59);
    assert.equal(picker.clampUnit(unit, 1000), 59);
    assert.equal(picker.clampUnit(unit, -1), 0);
  }
});
test('接受原有 1990～2100 年邊界', () => {
  for (const value of ['1990-01-01T00:00:00', '2100-12-31T23:59:59']) {
    assert.equal(picker.formatValue(picker.parseValue(value)), value);
  }
});
test('閏日有效性及無效日期、時間會被拒絕', () => {
  assert.equal(picker.formatValue(picker.parseValue('2000-02-29T12:00:00')), '2000-02-29T12:00:00');
  for (const value of ['1989-12-31T23:59:59', '2101-01-01T00:00:00', '2100-02-29T12:00:00', '2026-04-31T00:00:00', '2026-13-01T00:00:00', '2026-10-27T24:00:00', '2026-10-27T23:60:00', '2026-10-27T23:59:60']) {
    assert.throws(() => picker.parseValue(value), Error, value);
  }
});
