const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2] || require('node:path').join(__dirname, '../webapp/index.html'), 'utf8');
const source = html.slice(html.indexOf('async function openDetail('), html.indexOf('// ===== PRODUCT REVIEWS ====='));
async function check(outOfStock) {
 const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], {style:{},classList:{add(v){this[v]=true},toggle(){}},parentElement:{classList:{toggle(){}}}}]));
 const errors=[];
 const context = {tg:{expand(){}}, trk(){}, api:async()=>({id:10,name:'Bodom uni 1000gr',price:170000,unit:'piece',out_of_stock:outOfStock,media:[]}), document:{getElementById:id=>nodes.get(id)||null},t:{perUnit:'{unit}',backBtn:'Orqaga',addToCart:'Savatga',soonTitle0:'Kutilmoqda',soonText0:'Tez orada'},priceHtml:()=> '170000',ketoBadgeHtml:()=>'',favorites:{},SOLD_OUT_NOTES:1,paintRestockBtn(){},updateBackButton(){},loadProductReviews(){},console:{error(...args){errors.push(args)}},showToast(){}};
 vm.createContext(context); vm.runInContext(source, context); await context.openDetail(10);
 assert.equal(errors.length,0,errors.map(a=>a.map(String).join(' ')).join('\n'));
 assert.equal(nodes.get('detail-modal').classList.show,true,'product detail must open');
 assert.equal(nodes.get('detail-soon').hidden,!outOfStock,'availability note must match product stock');
}
(async()=>{await check(false);await check(true);console.log('PASS: available and sold-out products open with correct availability note')})().catch(e=>{console.error(e);process.exit(1)});
