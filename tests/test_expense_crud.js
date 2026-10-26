// Run actual expense UI handlers with only the network/DOM boundary replaced.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=fs.readFileSync('webapp/admin.html','utf8');
const fields={name:{value:''},amount:{value:'',addEventListener(type,fn){this[type]=fn;}}};
const classes=new Set();
const nodes={};
for(const key of ['#expCount','#expEmpty','#expRows','#expModalTitle','#expAmountPreview','#expSaveBtn','#newExpBtn']){
  nodes[key]={style:{},addEventListener(type,fn){this[type]=fn;}};
}
nodes['#expModal']={classList:{add(x){classes.add(x);},remove(x){classes.delete(x);}}};
nodes['#expForm']={elements:{namedItem(name){return fields[name];}},reset(){fields.name.value='';fields.amount.value='';},
  addEventListener(type,fn){this[type]=fn;}};
let saved=[{id:325,name:'Bonus <test>',amount:1250000,created_at:'2026-10-25T11:07:31',editable:true},
  {id:326,name:'Kuryer',amount:25000,created_at:'2026-10-25T12:00:00',editable:false,delivery_order_id:749}];
const requests=[];
let acceptDelete=true;
const ctx=vm.createContext({console,Number,Date,Set,
  $:s=>nodes[s],
  fmt:n=>Number(n).toLocaleString('en-US').replaceAll(',',' ')+" so'm",
  esc:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
  confirm:()=>acceptDelete,
  closeModals(){classes.delete('open');},toast(){},loadDashboard(){},
  localStorage:{getItem:()=> 'expenses'},
  api:async(path,opts={})=>{
    requests.push({path,opts});
    if(!opts.method)return {expenses:saved.map(r=>({...r}))};
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
  ctx.openExpenseModal(325);
  assert.equal(fields.name.value,'Bonus <test>');
  assert.equal(fields.amount.value,1250000);
  assert.match(nodes['#expModalTitle'].textContent,/Tahrirlash|tahrirlash/);
  fields.amount.value='125000';
  fields.amount.input?.();
  assert.equal(nodes['#expAmountPreview'].textContent,"125 000 so'm");
  await nodes['#expForm'].submit({target:nodes['#expForm'],preventDefault(){}});
  assert.equal(saved.find(r=>r.id===325).amount,125000);
  assert.equal(requests.find(r=>r.path==='/admin/api/expenses/325').opts.method,'POST');
  assert.equal(classes.has('open'),false);
  ctx.openExpenseModal(null);
  assert.equal(fields.name.value,'');assert.equal(fields.amount.value,'');
  fields.name.value='Yangi chiqim';fields.amount.value='59000';
  await nodes['#expForm'].submit({target:nodes['#expForm'],preventDefault(){}});
  assert.equal(saved.find(r=>r.id===900).amount,59000);
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
}
main().catch(err=>{console.error(err);process.exitCode=1;});
