param(
  [string]$CodepackPath = "RPGenesis-Fantasy.codepack.txt",
  [string]$OutHtml = "repo_explorer_embedded.html",
  [string]$Title = "RPGenesis Repo Explorer"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $CodepackPath)) {
  throw "Codepack not found at '$CodepackPath'."
}

# Read and embed the entire codepack as a JSON string for safe JS usage
$codepackText = Get-Content -Raw -Encoding UTF8 $CodepackPath
$embedded = ConvertTo-Json $codepackText -Compress

# Extract file paths from the codepack markers
function Extract-Paths([string]$text){
  $regex = [regex]'(?m)^-----8<----- FILE: (.+?) -----$'
  $matches = $regex.Matches($text)
  return $matches | ForEach-Object { $_.Groups[1].Value.Replace('\','/') }
}
$paths = Extract-Paths $codepackText

# Build a nested tree for the UI
function Make-Tree([string[]]$paths){
  $root = @{}
  foreach($p in $paths){
    $parts = $p.Split('/') | Where-Object { $_ -ne '' }
    $cur = $root
    for($i=0; $i -lt $parts.Length; $i++){
      $name = $parts[$i]
      $isFile = ($i -eq $parts.Length-1)
      if($isFile){
        if(-not $cur.ContainsKey('__files__')){ $cur['__files__'] = @() }
        $cur['__files__'] += $name
      } else {
        if(-not $cur.ContainsKey($name)){ $cur[$name] = @{} }
        $cur = $cur[$name]
      }
    }
  }
  return $root
}
function To-Nodes([string]$name, [hashtable]$node){
  $children = @()
  $keys = $node.Keys | Where-Object { $_ -ne '__files__' } | Sort-Object
  foreach($k in $keys){
    $children += (To-Nodes -name $k -node $node[$k])
  }
  if($node.ContainsKey('__files__')){
    foreach($f in ($node['__files__'] | Sort-Object)){
      $children += @{ name = $f; type = 'file' }
    }
  }
  return @{ name = $name; type = 'dir'; children = $children }
}
$tree = Make-Tree $paths
$rootNode = To-Nodes -name "RPGenesis-Fantasy" -node $tree
$rootJson = ($rootNode | ConvertTo-Json -Depth 50 -Compress)

# Build the HTML (uses Highlight.js via CDN for syntax highlighting)
$html = @"
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>$Title</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<style>
  :root{--bg:#0f1115;--panel:#151821;--muted:#7c869a;--fg:#e7e9ee;--acc:#7ab7ff}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Ubuntu}
  .wrap{display:flex;height:100%;}
  .sidebar{width:360px;max-width:48vw;background:var(--panel);border-right:1px solid #222;overflow:auto;padding:12px}
  .main{flex:1;padding:16px 20px;overflow:auto}
  h1{font-size:18px;margin:0 0 8px}
  .search{display:flex;gap:8px;margin-bottom:12px}
  .search input{flex:1;background:#0e1015;border:1px solid #2a2f3a;color:var(--fg);padding:8px 10px;border-radius:8px;outline:none}
  .counts{color:var(--muted);font-size:12px;margin:6px 0 12px}
  ul.tree{list-style:none;padding-left:14px;margin:0}
  .node{cursor:pointer;user-select:none;display:flex;align-items:center;gap:6px;padding:2px 4px;border-radius:6px}
  .node:hover{background:#1b2030}
  .file,.dir{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .file{color:#d5dbff}
  .dir{color:#9ed0ff;font-weight:600}
  .hidden{display:none}
  .pill{display:inline-block;background:#1a2233;color:#9ec3ff;border:1px solid #2b3b57;border-radius:999px;padding:4px 10px;font-size:12px;margin-right:6px}
  .footer{color:var(--muted);font-size:12px;margin-top:14px}
  code{display:block}
  pre#preview{background:#0e1015;border:1px solid #2a2f3a;border-radius:10px;padding:12px;min-height:40vh;overflow:auto}
</style>
</head>
<body>
<div class="wrap">
  <div class="sidebar">
    <h1>$Title</h1>
    <div class="search">
      <input id="q" placeholder="Filter files/folders… (e.g. data/npcs or .json or citizens)" />
    </div>
    <div class="counts">
      <span class="pill" id="countFiles">Files: …</span>
      <span class="pill" id="countDirs">Folders: …</span>
      <span class="pill" id="countShown">Shown: …</span>
    </div>
    <div id="tree"></div>
    <div class="footer">Click folders to expand/collapse. Type to filter; <code>Esc</code> to clear.</div>
  </div>
  <div class="main">
    <h2 id="selPath">Select a file</h2>
    <pre><code id="code" class=""></code></pre>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/json.min.js"></script>

<script>
// Embedded codepack and tree
const codepackText = $embedded;
const data = $rootJson;

const markerPrefix = "-----8<----- FILE: ";
const markerSuffix = " -----";

function extOf(path){
  const i = path.lastIndexOf(".");
  return i>=0 ? path.slice(i+1).toLowerCase() : "";
}

function classForExt(ext){
  if (ext === "py")   return "language-python";
  if (ext === "json") return "language-json";
  return ""; // plaintext
}

function findFileFromCodepack(path){
  const variants = [path, path.replaceAll('/','\\\\')];
  for (const v of variants) {
    const marker = markerPrefix + v + markerSuffix;
    const idx = codepackText.indexOf(marker);
    if (idx >= 0) {
      let start = codepackText.indexOf("\\n", idx);
      if (start < 0) return null;
      start += 1;
      let next = codepackText.indexOf(markerPrefix, start);
      if (next < 0) next = codepackText.indexOf("===== END OF CODEPACK =====", start);
      if (next < 0) next = codepackText.length;
      return codepackText.slice(start, next).trim();
    }
  }
  return null;
}

function countNodes(node){
  let files=0, dirs=1;
  for (const ch of node.children || []) {
    if (ch.type === 'file') files++;
    else if (ch.type === 'dir') { const c = countNodes(ch); files+=c.files; dirs+=c.dirs; }
  }
  return {files, dirs};
}

function render(node, path=""){
  const ul = document.createElement('ul');
  ul.className = 'tree';
  for (const ch of node.children) {
    const li = document.createElement('li');
    const row = document.createElement('div');
    row.className = 'node';

    const isDir = ch.type === 'dir';
    const nameSpan = document.createElement('span');
    nameSpan.textContent = ch.name + (isDir ? '/' : '');
    nameSpan.className = isDir ? 'dir' : 'file';

    row.appendChild(nameSpan);
    li.appendChild(row);

    const fullPath = path ? (path + '/' + ch.name) : ch.name;

    if (isDir) {
      const childUL = render(ch, fullPath);
      childUL.classList.add('hidden');
      li.appendChild(childUL);
      row.addEventListener('click', () => {
        const open = childUL.classList.toggle('hidden');
      });
    } else {
      row.addEventListener('click', () => {
        document.getElementById('selPath').textContent = fullPath;
        const text = findFileFromCodepack(fullPath) || "";
        const code = document.getElementById('code');
        code.className = classForExt(extOf(fullPath));
        code.textContent = text;
        if (code.className) { hljs.highlightElement(code); }
      });
    }
    li.dataset.name = ch.name.toLowerCase();
    li.dataset.path = fullPath.toLowerCase();
    li.dataset.type = ch.type;
    ul.appendChild(li);
  }
  return ul;
}

function buildTree(){
  const container = document.getElementById('tree');
  container.innerHTML = "";
  const ul = render(data, "");
  container.appendChild(ul);

  const c = countNodes(data);
  document.getElementById('countFiles').textContent = 'Files: ' + c.files;
  document.getElementById('countDirs').textContent = 'Folders: ' + c.dirs;

  const q = document.getElementById('q');
  function applyFilter(){
    const term = q.value.trim().toLowerCase();
    let shown = 0;
    container.querySelectorAll('li').forEach(li=>{
      const match = !term || li.dataset.path.includes(term) || li.dataset.name.includes(term);
      li.style.display = match ? "" : "none";
      if (match) shown++;
      if (match) {
        // auto-open parent folders for matches
        let p = li.parentElement;
        while (p && p.classList.contains('tree')) {
          const prev = p.previousSibling;
          if (prev && prev.classList && prev.classList.contains('node')) {
            // ensure visible
          }
          p.classList.remove('hidden');
          p = p.parentElement ? p.parentElement.closest('.tree') : null;
        }
      }
    });
    document.getElementById('countShown').textContent = 'Shown: ' + shown;
  }
  q.addEventListener('input', applyFilter);
  q.addEventListener('keydown', (e)=>{ if (e.key==='Escape'){ q.value=''; applyFilter(); } });
  applyFilter();
}
buildTree();
</script>
</body>
</html>
"@

Set-Content -LiteralPath $OutHtml -Encoding UTF8 -Value $html
Write-Host "Built explorer: $OutHtml"
