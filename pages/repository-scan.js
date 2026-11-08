(() => {
  "use strict";

  async function github(path) {
    const response = await fetch("https://api.github.com/" + path, {signal:AbortSignal.timeout(15000)});
    if(response.status===404) throw Error("הריפו או הענף לא נמצאו, או שהריפו פרטי. בגרסת האתר הסריקה זמינה לריפו ציבורי.");
    if(response.status===403 || response.status===429) throw Error("GitHub הגביל זמנית את הסריקה. נסה שוב מאוחר יותר.");
    if(!response.ok) throw Error("GitHub לא החזיר את קבצי המקור. נסה שוב.");
    return response.json();
  }

  function selectFiles(tree) {
    const readable=tree.filter(f=>f.type==="blob" && f.size<=150000);
    const choose=patterns=>patterns.flatMap(pattern=>readable.filter(f=>pattern.test(f.path)).slice(0,3));
    return [...new Set(choose([
      /^README(?:\.[^/]+)?$/i,/^package\.json$/i,/^\.github\/workflows\/[^/]+\.ya?ml$/,
      /^(?:vite\.config\.[^/]+|index\.html|pyproject\.toml)$/,
      /^src\/(?:main|app|course|platform|familySync|engine)\.[jt]sx?$/i,
      /^src\/(?:styles|index)\.css$/i,/^src\/[^/]+\/(?:engine|lessons|storage|tokens)\.[jt]sx?$/i
    ]))].slice(0,20);
  }

  async function scan(repoUrl, branch) {
    let url;
    try {url=new URL(repoUrl);} catch {throw Error("הזן בכרטיס הפרויקט כתובת לריפו ציבורי ב־GitHub.");}
    const match=url.pathname.match(/^\/([\w.-]+)\/([\w.-]+)(?:\/|$)/);
    if(url.origin!=="https://github.com" || !match) throw Error("הזן בכרטיס הפרויקט כתובת לריפו ציבורי ב־GitHub.");
    const owner=match[1], name=match[2].replace(/\.git$/,""), repo=owner+"/"+name;
    const root="repos/"+encodeURIComponent(owner)+"/"+encodeURIComponent(name);
    const metadata=branch ? null : await github(root);
    const ref=branch || metadata.default_branch;
    const commit=await github(root+"/commits/"+encodeURIComponent(ref));
    const tree=await github(root+"/git/trees/"+commit.commit.tree.sha+"?recursive=1");
    const files=selectFiles(tree.tree);
    const samples=await Promise.allSettled(files.map(async file=>{
      const path=[owner,name,commit.sha,...file.path.split("/")].map(encodeURIComponent).join("/");
      const res=await fetch("https://raw.githubusercontent.com/"+path,{signal:AbortSignal.timeout(12000)});
      if(!res.ok) throw Error(file.path);
      return {path:file.path,text:(await res.text()).slice(0,20000)};
    }));
    const inspected=samples.filter(x=>x.status==="fulfilled").map(x=>x.value);
    if(!inspected.length) throw Error("נמצא commit, אבל קבצי המקור לא נטענו. נסה שוב.");
    const pkgText=inspected.find(f=>f.path==="package.json")?.text;
    let pkg={};
    try {pkg=JSON.parse(pkgText ?? "{}");} catch {}
    const readme=inspected.find(f=>/^README/i.test(f.path));
    const modules=tree.tree.filter(f=>f.type==="tree" && /^src\/[^/]+$/.test(f.path)).map(f=>f.path);
    const styles=inspected.filter(f=>f.path.endsWith(".css"));
    const tokens=[...new Set(styles.flatMap(f=>[...f.text.matchAll(/(--[a-z][\w-]*)\s*:/gi)].map(m=>m[1])))].slice(0,14);
    const workflows=inspected.filter(f=>f.path.startsWith(".github/workflows/"));
    const tests=tree.tree.filter(f=>f.type==="blob" && /(?:\.test\.|\.spec\.|^tests\/)/.test(f.path)).length;
    const report={
      repo, branch:ref, revision:commit.sha, files:inspected.map(f=>f.path), truncated:!!tree.truncated,
      summary:[
        "מאגר: "+repo+" · ענף: "+ref,
        metadata?.description || pkg.description || "",
        readme ? "פתיחת README:\n"+readme.text.split("\n").filter(x=>x.trim()).slice(0,6).join("\n").slice(0,1700) : ""
      ].filter(Boolean).join("\n\n"),
      architecture:[
        "מיפוי ראשוני לפי קבצי המקור שנקראו.",
        Object.keys(pkg.dependencies ?? {}).length ? "תלויות: "+Object.keys(pkg.dependencies).slice(0,16).join(", ") : "",
        modules.length ? "מודולים: "+modules.slice(0,20).join(", ") : "",
        "קובצי בדיקות שזוהו בעץ: "+tests,
        workflows.length ? "פריסה ו־CI: "+workflows.map(f=>f.path).join(", ") : ""
      ].filter(Boolean).join("\n"),
      design:[
        "מיפוי עיצוב ראשוני מהקוד. בדיקה חזותית דורשת פתיחה של האתר או Preview.",
        styles.length ? "קובצי סגנון: "+styles.map(f=>f.path).join(", ") : "",
        tokens.length ? "משתני עיצוב לדוגמה: "+tokens.join(", ") : ""
      ].filter(Boolean).join("\n"),
      recommendations:"אמת את זרימות המשתמש באתר הפעיל. תעד את הגבול בין תוכן לתשתית ואת הבדיקות הנדרשות לפני שינויים."
    };
    try {
      const reviewed=await fetch("./repository-reviews.json");
      if(reviewed.ok){
        const baseline=(await reviewed.json())[repo.toLowerCase()+"@"+commit.sha];
        if(baseline) Object.assign(report,baseline,{files:[...new Set([...report.files,...baseline.files])]});
      }
    } catch {}
    return report;
  }

  async function reviewDiff(pr, revision, repository) {
    let url, repo;
    try { url=new URL(pr); if(repository) repo=new URL(repository); } catch {}
    const match=url?.pathname.match(/^\/([\w.-]+)\/([\w.-]+)\/pull\/(\d+)\/?$/);
    if(url?.origin!=="https://github.com" || !match) throw Error("נדרש קישור ל־Pull Request ב־GitHub.");
    if(repository && (repo?.origin!=="https://github.com" || repo.pathname.split("/").slice(1,3).join("/").replace(/\.git$/,"").toLowerCase()!==(match[1]+"/"+match[2]).toLowerCase()))
      throw Error("ה־Pull Request אינו שייך לריפו של הפרויקט.");
    const endpoint="repos/"+match[1]+"/"+match[2]+"/pulls/"+match[3];
    const head=await github(endpoint);
    if(head.head?.sha!==revision) throw Error("ראש ה־PR השתנה. הגש לסקירה את ה־SHA הנוכחי.");
    if(head.changed_files<1 || head.changed_files>100) throw Error("היקף השינוי דורש סקירת קוד ידנית.");
    const files=await github(endpoint+"/files?per_page=100");
    const after=await github(endpoint);
    if(after.head?.sha!==revision || after.base?.sha!==head.base?.sha)
      throw Error("גרסת ה־PR השתנתה במהלך טעינת ה־diff.");
    let size=0;
    for(const file of files){
      const lines=(file.patch ?? "").split("\n");
      if(!file.patch || lines.filter(line=>line.startsWith("+")).length!==file.additions ||
         lines.filter(line=>line.startsWith("-")).length!==file.deletions)
        throw Error("ה־diff של GitHub חלקי. נדרשת סקירת קוד ידנית.");
      size+=file.patch.length;
    }
    if(files.length!==head.changed_files || size>45000) throw Error("ה־diff גדול או חלקי. נדרשת סקירת קוד ידנית.");
    return files.map(({filename,status,patch})=>({filename,status,patch}));
  }

  window.AgentHubRepository = {scan,reviewDiff};
})();
