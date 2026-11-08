// Run actual expense UI handlers with only the network/DOM boundary replaced.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=fs.readFileSync('webapp/admin.html','utf8');
const fields={name:{value:''},amount:{value:'',addEventListener(type,fn){this[type]=fn;}}};
const classes=new Set();
const nodes={};
for(const key of ['#expCount','#expEmpty','#expRows','#expModalTitle','#expAmountPreview','#expSaveBtn','#newExpBtn',
  '#expCatFilter','#expCatsBtn','#expCatQuickAdd','#expCatNew','#expCatNewBtn','#expCatList']){
  nodes[key]={style:{},value:'',addEventListener(type,fn){this[type]=fn;}};
}
nodes['#expTotals']={innerHTML:'',querySelectorAll(){return [];}};
// A <select>: keeps a value only if an option with it exists.
nodes['#expCategory']={_v:'',innerHTML:'',get value(){return this._v;},
  set value(v){this._v=(v===''||this.innerHTML.includes(`value="${v}"`))?v:'';}};
nodes['#expModal']={classList:{add(x){classes.add(x);},remove(x){classes.delete(x);}}};
nodes['#expCatModal']={classList:{add(x){classes.add('cat-'+x);},remove(x){classes.delete('cat-'+x);}}};
nodes['#expForm']={elements:{namedItem(name){return fields[name];}},reset(){fields.name.value='';fields.amount.value='';},
  addEventListener(type,fn){this[type]=fn;}};
let saved=[{id:325,name:'Bonus <test>',amount:1250000,created_at:'2026-10-25T11:07:31',editable:true,category_id:3,category_name:'Reklama'},
  {id:326,name:'Kuryer',amount:25000,created_at:'2026-10-25T12:00:00',editable:false,delivery_order_id:749,
   category_name:'🚚 Kuryer (avtomatik)'}];
let cats=[{id:3,name:'Reklama',uses:1}];
const requests=[];
let acceptDelete=true;
let promptAnswer='';
const ctx=vm.createContext({console,Number,Date,Set,Promise,encodeURIComponent,String,
  $:s=>nodes[s],
  fmt:n=>Number(n).toLocaleString('en-US').replaceAll(',',' ')+" so'm",
  esc:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
  confirm:()=>acceptDelete,prompt:()=>promptAnswer,
  closeModals(){classes.delete('open');},toast(){},loadDashboard(){},
  localStorage:{getItem:()=> 'expenses'},
  api:async(path,opts={})=>{
    requests.push({path,opts});
    if(path.startsWith('/admin/api/expense-categories')){
      if(!opts.method)return {categories:cats.map(c=>({...c}))};
      const body=opts.body?JSON.parse(opts.body):{};
      const old=cats.find(c=>c.name.toLowerCase()===body.name.toLowerCase());
      if(old)return {ok:true,id:old.id,created:false};
      cats.push({id:7,name:body.name,uses:0});return {ok:true,id:7,created:true};
    }
    if(path.startsWith('/admin/api/expenses/by-category'))
      return {totals:[{key:'3',name:'Reklama',total:1250000,count:1}]};
    if(!opts.method){
      const m=/category=(\d+)/.exec(path);
      const rows=m?saved.filter(r=>String(r.category_id)===m[1]):saved;
      return {expenses:rows.map(r=>({...r}))};
    }
    const body=opts.body?JSON.parse(opts.body):{};
    if(path.endsWith('/delete')){const id=+path.split('/').at(-2);saved=saved.filter(r=>r.id!==id);return {ok:true};}
    const id=+path.split('/').at(-1);
    if(Number.isFinite(id)){Object.assign(saved.find(r=>r.id===id),body);return {ok:true};}
    saved.push({id:900,...body,editable:true});return {ok:true,id:900};
  },
});
ctx.window=ctx;
vm.runInContext(html.split('/* ===== expenses ===== */')[1].split('/* ===== faollik:')[0],ctx);
async function main(){
  assert.equal(typeof ctx.openExpenseModal,'function','Expenses need a create/edit form');
  assert.equal(typeof ctx.deleteExpense,'function','Expenses need delete with confirmation');
  await ctx.loadExpenses();
  assert.match(nodes['#expRows'].innerHTML,/Bonus &lt;test&gt;/);
  assert.match(nodes['#expRows'].innerHTML,/openExpenseModal\(325\)/);
  assert.doesNotMatch(nodes['#expRows'].innerHTML,/openExpenseModal\(326\)/);
  // Kategoriya: column, filter options, the period totals strip.
  assert.match(nodes['#expRows'].innerHTML,/class="exp-cat">Reklama/);
  assert.match(nodes['#expRows'].innerHTML,/Kuryer \(avtomatik\)/);
  assert.match(nodes['#expCatFilter'].innerHTML,/value="3"[^>]*>Reklama/);
  assert.match(nodes['#expCatFilter'].innerHTML,/value="none"/);
  await new Promise(r=>setTimeout(r,0));
  assert.match(nodes['#expTotals'].innerHTML,/Reklama <b>1 250 000 so'm<\/b>/);
  ctx.openExpenseModal(325);
  assert.equal(fields.name.value,'Bonus <test>');
  assert.equal(fields.amount.value,1250000);
  assert.equal(nodes['#expCategory'].value,'3','Editing keeps the expense category');
  assert.match(nodes['#expModalTitle'].textContent,/Tahrirlash|tahrirlash/);
  fields.amount.value='125000';
  fields.amount.input?.();
  assert.equal(nodes['#expAmountPreview'].textContent,"125 000 so'm");
  await nodes['#expForm'].submit({target:nodes['#expForm'],preventDefault(){}});
  assert.equal(saved.find(r=>r.id===325).amount,125000);
  assert.equal(JSON.parse(requests.find(r=>r.path==='/admin/api/expenses/325').opts.body).category_id,3);
  assert.equal(requests.find(r=>r.path==='/admin/api/expenses/325').opts.method,'POST');
  assert.equal(classes.has('open'),false);
  ctx.openExpenseModal(null);
  assert.equal(fields.name.value,'');assert.equal(fields.amount.value,'');
  assert.equal(nodes['#expCategory'].value,'','A new expense starts without a category');
  // A new category straight from the form is picked for the new expense.
  promptAnswer='Ijara';
  await nodes['#expCatQuickAdd'].click();
  assert.equal(nodes['#expCategory'].value,'7');
  fields.name.value='Yangi chiqim';fields.amount.value='59000';
  await nodes['#expForm'].submit({target:nodes['#expForm'],preventDefault(){}});
  assert.equal(saved.find(r=>r.id===900).amount,59000);
  assert.equal(saved.find(r=>r.id===900).category_id,7);
  // Filter: the list is asked for one category.
  nodes['#expCatFilter'].change({target:{value:'3'}});
  await new Promise(r=>setTimeout(r,0));
  assert.ok(requests.some(r=>r.path==='/admin/api/expenses?category=3'));
  acceptDelete=false;
  await ctx.deleteExpense(325);
  assert.ok(saved.some(r=>r.id===325));
  acceptDelete=true;
  await ctx.deleteExpense(326);
  assert.ok(saved.some(r=>r.id===326),'Automatic expenses must stay protected in the UI');
  await ctx.deleteExpense(325);
  assert.ok(!saved.some(r=>r.id===325));
  assert.equal(nodes['#expSaveBtn'].disabled,false);
  console.log('Expense CRUD: render, edit correction, create reset, amount preview, delete confirmation and automatic protection passed');
  console.log('Expense categories: column, filter, totals, quick add from the form, category kept on edit passed');
}
main().catch(err=>{console.error(err);process.exitCode=1;});
