// login.js
document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault(); // stay on the page
  
    const fd = new FormData(e.target);
    const res = await fetch("/api/signin/", { method: "POST", body: fd });
    let data = {};
    try { data = await res.json(); } catch {}
  
    if (res.ok && data.ok) {
      // ✅ logged in: send the user to the dashboard
      window.location.href = "/dashboard/";
    } else {
      // show a simple error under the form (optional)
      const p = document.getElementById("login-status") || document.createElement("p");
      p.id = "login-status";
      p.style.color = "crimson";
      p.textContent = (data && data.error) ? data.error : `Login failed (${res.status})`;
      e.target.after(p);
    }
  });
  