const fs = require('fs');
const path = require('path');
const ts = require('./typescript-5.4.5.js');
const files = {
 numArray:'cinar_src_helper_numArray.ts',
 exponentialMovingAverage:'cinar_src_indicator_trend_exponentialMovingAverage.ts',
 forceIndex:'cinar_src_indicator_volume_forceIndex.ts',
 forceIndexStrategy:'cinar_examples_volume_forceIndexStrategy.ts',
 action:'cinar_src_strategy_action.ts', asset:'cinar_src_strategy_asset.ts',
};
const cache = {};
function load(name) {
  if (cache[name]) return cache[name].exports;
  if (!files[name]) throw new Error('Unbound source dependency: '+name);
  const filename = path.join(__dirname, files[name]);
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    fileName: filename,
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
    reportDiagnostics: true,
  });
  if ((compiled.diagnostics || []).some(d=>d.category === ts.DiagnosticCategory.Error)) {
    throw new Error('Source compilation failed');
  }
  const module = { exports: {} }; cache[name] = module;
  new Function('require', 'module', 'exports', compiled.outputText)(
    specifier=>load(path.posix.basename(specifier)), module, module.exports);
  return module.exports;
}
const fixtures = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const indicator=load('forceIndex');
const strategy=load('forceIndexStrategy');
const out=fixtures.map(f=>({indicator:indicator.fi(f.closings,f.volumes),actions:strategy.fiStrategy(f)}));
fs.writeFileSync(process.argv[3],JSON.stringify({node:process.version,typescript:ts.version,out}));
