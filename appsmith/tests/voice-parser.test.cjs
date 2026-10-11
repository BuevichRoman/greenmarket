const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync(process.argv[2] || 'appsmith/seller-catalog-widget.html', 'utf8');
const start = html.indexOf('  /* GM-VOICE-001 parser — tested directly from this widget source. */');
const end = html.indexOf('  function App() {', start);
assert.ok(start >= 0 && end > start, 'Voice parsers must be present in widget source');

const context = {};
vm.createContext(context);
vm.runInContext(html.slice(start, end), context);

const products = [
  {id:1, product_name:'Яблоки Гала', catalog_name:'Яблоки Гала', unit:'кг', price:100, stock:10},
  {id:2, product_name:'Яблоки Голден', catalog_name:'Яблоки Голден', unit:'кг', price:110, stock:20},
  {id:3, product_name:'Молоко', catalog_name:'Молоко', unit:'л', price:90, stock:5}
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

r = context.voiceParseStockCommand('Продал 2 кг Яблоки Гала', products);
assert.equal(r.type, 'STOCK_OPERATION');
assert.equal(r.operation, 'SALE');
assert.equal(r.product.id, 1);
assert.equal(r.quantity, 2);
assert.equal(r.unit, 'кг');

r = context.voiceParseStockCommand('Принял 1,250 кг Яблоки Гала', products);
assert.equal(r.type, 'STOCK_OPERATION');
assert.equal(r.operation, 'INCOMING');
assert.equal(r.quantity, 1.25, 'stock quantities support three decimal places');

r = context.voiceParseStockCommand('Продал две кг Молоко', products);
assert.equal(r.type, 'UNIT_MISMATCH');
assert.equal(r.unit, 'кг', 'unit mismatch must be rejected before confirmation');

r = context.voiceParseStockCommand('Продал 2 л Молоко', products);
assert.equal(r.type, 'STOCK_OPERATION');
assert.equal(r.operation, 'SALE');
assert.equal(r.unit, 'л');

r = context.voiceParseStockCommand('Принял 2 л Молока', products);
assert.equal(r.type, 'STOCK_OPERATION', 'inflected product names must resolve');
assert.equal(r.operation, 'INCOMING');
assert.equal(r.product.id, 3);

r = context.voiceParseStockCommand('Продал 2 кг Яблоки', products);
assert.equal(r.type, 'AMBIGUOUS_STOCK');
assert.equal(r.matches.length, 2, 'ambiguous stock item must require explicit selection');

r = context.voiceParseStockCommand('Продал 0 кг Молоко', products);
assert.equal(r.type, 'INVALID_QUANTITY');

r = context.voiceParseStockCommand('Продал 2 кг Несуществующий товар', products);
assert.equal(r.type, 'NOT_FOUND');

console.log('GreenMarket voice parser tests passed: 15 cases');
