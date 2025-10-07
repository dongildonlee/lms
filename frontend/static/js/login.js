// /static/js/login.js
(function () {
  console.log("[login] script loaded");
  window._login_boot = true;

  // Find a plausible login form
  const form =
    document.getElementById("login-form") ||
    document.querySelector('form[data-login]') ||
    document.querySelector('form[action*="signin"]') ||
    document.querySelector("form");

  if (!form) {
    console.warn("[login] no form found");
    return;
  }

  const DASHBOARD_CANDIDATES = [
    "/dashboard",
    "/pages/dashboard.html",
    "/frontend/pages/dashboard.html",
    "/dashboard.html",
  ];

  function getCSRF() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function resolveDashboard(preferred) {
    const list = preferred ? [preferred, ...DASHBOARD_CANDIDATES] : DASHBOARD_CANDIDATES;
    for (const path of list) {
      try {
        const r = await fetch(path, { cache: "no-store", credentials: "same-origin" });
        const ct = (r.headers.get("content-type") || "").toLowerCase();
        if (r.ok && ct.includes("text/html")) return path;
      } catch {}
    }
    return "/";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const fd = new FormData(form);
    const headers = {
      "X-Requested-With": "XMLHttpRequest",
      "X-CSRFToken": fd.get("csrfmiddlewaretoken") ? undefined : getCSRF(),
    };
    if (!headers["X-CSRFToken"]) delete headers["X-CSRFToken"];

    let res;
    try {
      res = await fetch("/api/signin/", {
        method: "POST",
        body: fd,
        headers,
        credentials: "same-origin",
        redirect: "follow",
      });
    } catch (err) {
      console.error("[login] network error:", err);
      alert("Network error: " + (err?.message || err));
      return;
    }

    console.log("[login] /api/signin/ →", res.status, res.redirected ? "(redirected)" : "");
    const ct = (res.headers.get("content-type") || "").toLowerCase();

    if (res.redirected) {
      window.location.href = res.url;
      return;
    }

    if (ct.includes("text/html")) {
      // backend returned HTML directly
      document.open(); document.write(await res.text()); document.close();
      return;
    }

    let data = {};
    if (ct.includes("application/json")) {
      try { data = await res.json(); } catch {}
    }

    if (res.ok && (data.ok === true || data.ok === "true")) {
      const target = await resolveDashboard(data.redirect);
      console.log("[login] redirecting to", target);
      window.location.href = target;
      return;
    }

    const msg = (data && (data.error || data.detail)) || `Login failed (${res.status})`;
    console.warn("[login]", msg);
    const p = document.getElementById("login-status") || document.createElement("p");
    p.id = "login-status";
    p.style.color = "crimson";
    p.style.marginTop = "8px";
    p.textContent = msg;
    form.after(p);
  });
})();


  