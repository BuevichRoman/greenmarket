const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2] || 'appsmith/seller-catalog-widget.html', 'utf8');
const start = html.indexOf('  /* GM-VOICE-001 parser — tested directly from this widget source. */');
const end = html.indexOf('  function App() {', start);
assert.ok(start >= 0 && end > start, 'Parser must be present in widget source');
const context = {};
vm.createContext(context);
vm.runInContext(html.slice(start, end), context);
const products = [
  {id:1, product_name:'Яблоки Гала', catalog_name:'Яблоки Гала', unit:'кг', price:100},
  {id:2, product_name:'Яблоки Голден', catalog_name:'Яблоки Голден', unit:'кг', price:110},
  {id:3, product_name:'Молоко', catalog_name:'Молоко', unit:'л', price:90}
];
let r = context.voiceParseCommand('Поставь молоко по 120 рублей за килограмм', products);
assert.equal(r.type, 'SET_PRICE');
assert.equal(r.unit, 'кг');
assert.notEqual(context.voiceUnit(r.unit), context.voiceUnit(r.product.unit), 'caller must reject wrong unit');
r = context.voiceParseCommand('Поставь яблоки Гала по 120 рублей', products);
assert.equal(r.type, 'SET_PRICE');
assert.equal(r.product.id, 1, 'exact product name must beat partial matches');
r = context.voiceParseCommand('Поставь молоко по 89,90 рублей', products);
assert.equal(r.type, 'SET_PRICE');
assert.equal(r.price, 89.9);
r = context.voiceParseCommand('Поставь молоко цену 120', products);
assert.equal(r.type, 'SET_PRICE');
assert.equal(r.price, 120);
assert.equal(context.voiceUnit('килограмма'), 'кг');
assert.equal(context.voiceUnit('грамма'), 'г');
r = context.voiceParseCommand('Найди молоко', products);
assert.equal(r.type, 'SEARCH');
assert.equal(r.query, 'молоко');
r = context.voiceParseCommand('Поставь яблоки по 120 рублей', products);
assert.equal(r.type, 'AMBIGUOUS');
assert.equal(r.matches.length, 2, 'ambiguous choices must be surfaced');
console.log('GM-VOICE-001 widget parser tests passed: 8 cases');
