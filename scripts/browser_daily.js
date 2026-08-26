// 在已登录的 https://picix.us 页面打开 F12 Console，整段粘贴回车。
// 会用当前浏览器 IndexedDB 里的私钥给每次请求签名，完成今日领取+解锁。
(async () => {
  const LIST_IDS = [1, 8];
  const token = localStorage.getItem("token");
  const sessionId = localStorage.getItem("auth-session-id");
  if (!token || !sessionId) {
    throw new Error("未登录：localStorage 缺少 token 或 auth-session-id，请先重新登录。");
  }

  const db = await new Promise((resolve, reject) => {
    const req = indexedDB.open("picix-auth", 1);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("无法打开 picix-auth"));
  });
  const rec = await new Promise((resolve, reject) => {
    const req = db.transaction("proof-keys", "readonly").objectStore("proof-keys").get(sessionId);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("无法读取 proof key"));
  });
  const privateKey = rec && rec.privateKey;
  if (!privateKey) {
    throw new Error("IndexedDB 里没有当前会话的私钥，请在本机原浏览器重新登录后再试。");
  }

  const te = new TextEncoder();
  const b64url = (bytes) => {
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    let s = "";
    u8.forEach((b) => {
      s += String.fromCharCode(b);
    });
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  };
  const sha256hex = async (str) => {
    const buf = await crypto.subtle.digest("SHA-256", te.encode(str));
    return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
  };

  async function api(method, requestTarget, body) {
    const bodyStr = body == null ? "" : JSON.stringify(body);
    const time = Math.floor(Date.now() / 1000);
    const nonce = b64url(crypto.getRandomValues(new Uint8Array(16)));
    const [credHash, bodyHash] = await Promise.all([sha256hex(token), sha256hex(bodyStr)]);
    const msg = ["PICIX-PROOF-V1", credHash, method.toUpperCase(), requestTarget, bodyHash, String(time), nonce].join("\n");
    const sig = new Uint8Array(
      await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, privateKey, te.encode(msg)),
    );
    const headers = {
      accept: "application/json, text/plain, */*",
      authorization: token,
      "X-Picix-Proof-Time": String(time),
      "X-Picix-Proof-Nonce": nonce,
      "X-Picix-Proof-Signature": b64url(sig),
    };
    const init = { method, headers };
    if (body != null) {
      headers["content-type"] = "application/json";
      init.body = bodyStr;
    }
    const res = await fetch("/api" + requestTarget, init);
    const json = await res.json();
    if (!res.ok || json.success === false) {
      throw new Error(`${method} ${requestTarget} -> HTTP ${res.status} ${json.code || ""} ${json.msg || JSON.stringify(json).slice(0, 200)}`);
    }
    return json;
  }

  const taskCode = (t) => t.code || t.unique || "";
  const progressOf = (t) => t.progress || t.process || null;
  const isDone = (p) => {
    if (!p) return false;
    const st = String(p.status || "").toUpperCase();
    return ["COMPLETED", "FINISHED", "DONE", "CLAIMED"].includes(st) || p.isFinish === "Y";
  };

  const summarize = (tasks) => {
    const out = { daily_done: false, daily_accepted: false, monthly: 0, playlist: 0 };
    for (const t of tasks || []) {
      const code = taskCode(t);
      const p = progressOf(t);
      if (code === "D_UL_1") {
        out.daily_done = isDone(p);
        out.daily_accepted = Boolean(p);
      } else if (code === "M_UL_50") {
        out.monthly = Number((p && (p.progress ?? p.process)) || 0);
      } else if (code === "M_UL_ML_20") {
        out.playlist = Number((p && (p.progress ?? p.process)) || 0);
      }
    }
    return out;
  };

  const accept = async (code, label) => {
    try {
      const r = await api("POST", "/Tasks/accept", { code });
      console.log("领取成功", label, r.msg || r);
    } catch (err) {
      const text = String(err.message || err);
      if (text.includes("已领取") || text.includes("已接取")) {
        console.log("已领取过", label);
        return;
      }
      throw err;
    }
  };

  let tasks = (await api("GET", "/Tasks/list")).data || [];
  let sum = summarize(tasks);
  console.log("领取前", sum);

  for (const [code, label] of [
    ["M_UL_50", "月度50"],
    ["M_UL_ML_20", "片单20"],
  ]) {
    const t = tasks.find((x) => taskCode(x) === code);
    if (!progressOf(t)) await accept(code, label);
  }
  if (!sum.daily_done && !sum.daily_accepted) {
    await accept("D_UL_1", "每日解锁");
  }

  if (sum.daily_done) {
    const result = { ok: true, skipped: true, reason: "今日已完成", ...sum };
    console.log("RESULT", JSON.stringify(result, null, 2));
    return result;
  }

  const packageRemaining = async () => {
    const pkgs = (await api("GET", "/Packages/listMine")).data || [];
    return pkgs.reduce((n, p) => n + (p.total || 0) - (p.used || 0), 0);
  };
  const currentPoints = async () => {
    const hist = (await api("GET", "/Users/listPointHistory")).data || [];
    return (hist[0] && hist[0].totalPoints) || 0;
  };

  let remaining = await packageRemaining();
  console.log("资源包剩余", remaining);
  if (remaining <= 0) {
    const points = await currentPoints();
    const goodsResp = await api("GET", "/Malls/listGoods");
    const goods = goodsResp.data || goodsResp;
    const packages = goods.package || [];
    const pack = packages.find((g) => g.id === 1) || [...packages].sort((a, b) => (a.price || 0) - (b.price || 0))[0];
    if (!pack) throw new Error("商城没有可用的资源包商品。");
    if (points < pack.price) {
      throw new Error(`资源包已用完，积分 ${points} 不够买 ${pack.name}（需要 ${pack.price}）。`);
    }
    const clientRequestId = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("");
    console.log(`积分 ${points}，购买 ${pack.name} goodId=${pack.id}（${pack.price} 积分）`);
    await api("POST", "/Malls/payGood", { goodId: pack.id, clientRequestId });
    remaining = await packageRemaining();
    console.log("购买后资源包剩余", remaining);
    if (remaining <= 0) throw new Error("已购买资源包，但剩余次数仍为 0。");
  }

  let picked = null;
  for (const listId of LIST_IDS) {
    const data = (await api("GET", `/Movies/getMovieList?listId=${listId}`)).data || {};
    const movie = (data.list || []).find((m) => !m.isUnlock && m.id != null);
    if (movie) {
      picked = { id: movie.id, listId };
      break;
    }
  }
  if (!picked) throw new Error("收藏片单 1/8 里没有未解锁影片。");

  const unlocked = await api("POST", "/Movies/unlock", {
    movieId: Number(picked.id),
    fromMovieList: picked.listId,
  });
  console.log("解锁", picked, unlocked.msg || unlocked);

  tasks = (await api("GET", "/Tasks/list")).data || [];
  sum = summarize(tasks);
  const hist = (await api("GET", "/Users/listPointHistory")).data || [];
  const points = hist[0] && hist[0].totalPoints;
  const pkgs2 = (await api("GET", "/Packages/listMine")).data || [];
  const remaining2 = pkgs2.reduce((n, p) => n + (p.total || 0) - (p.used || 0), 0);

  const result = {
    ok: true,
    movie_id: picked.id,
    list_id: picked.listId,
    daily_done: sum.daily_done,
    monthly: sum.monthly,
    playlist: sum.playlist,
    points,
    package_remaining: remaining2,
  };
  console.log("RESULT", JSON.stringify(result, null, 2));
  return result;
})().catch((err) => {
  console.error("FAILED", err);
  throw err;
});
