// Log-in form
const lf = document.getElementById("login-form");
if (lf) lf.addEventListener("submit", (e) => {
    e.preventDefault(); // stop the page reload
    const u = document.getElementById("username").value;
    const p = document.getElementById("password").value;
    console.log("submitted:", {username: u, password: p.length ? "(entered)" : "(empty)"});
    const now = new Date().toLocaleString();
    // document.getElementById("status").textContent = `Attempting login as "${u}" at ${now}.`;
    const users = JSON.parse(localStorage.getItem("mockUsers") || "[]");
    const match = users.find(uo => uo.username.toLowerCase() === u.toLowerCase());
    const ok = !!match && match.password === p; //!! converts an object (like match) into a boolean
    const status = document.getElementById("status");
    if (!ok) {status.textContent = "Invalid username or password (mock)"; status.style.color="red"; return;}
    status.textContent = `Logged in as "${match.username}" (mock)`;
    status.style.color="green"
    localStorage.setItem("mockCurrentUser", match.username);
    // Add login history
    const eventsKey = "mockLoginEvents";
    const events = JSON.parse(localStorage.getItem(eventsKey) || "[]");
    events.push({username: match.username, at: new Date().toISOString()});
    localStorage.setItem(eventsKey, JSON.stringify(events));
    // Add login attempt
    const key = "loginAttempts";
    const attempts = JSON.parse(localStorage.getItem(key) || "[]");
    attempts.push(new Date().toISOString());
    localStorage.setItem(key, JSON.stringify(attempts))
    // Go to Home
    window.location.href = "home.html";
});

// Sign-up form
const sf = document.getElementById("signup-form");
if (sf) sf.addEventListener("submit" , (e) => {
    e.preventDefault();
    const p1v = document.getElementById("su-password").value;
    const p2v = document.getElementById("su-password2").value;
    if (p1v !== p2v){
        const msg = document.getElementById("pw-msg");
        if (msg) {
            msg.textContent = "Passwords do not match";
            msg.style.color = "red";
        }
        document.getElementById("su-password2").focus();
        return;
    }
    console.log("signup submit");
    const uname = document.getElementById("su-username").value.trim();
    document.getElementById("su-status").textContent = `Creating account for "${uname}"... (frontend only)`;
    // Add the new user to the database
    const userKey = "mockUsers";
    const users = JSON.parse(localStorage.getItem(userKey) || "[]");
    // Check if existing username
    if (users.some(u => u.username.toLowerCase() === uname.toLowerCase())){
        const s = document.getElementById("su-status");
        if (s) {
            s.textContent = 'that username is taken (mock)';
            s.style.color = 'red';
        }
        return;
    }
    users.push({username: uname, password: p1v});
    localStorage.setItem(userKey, JSON.stringify(users))
});

document.getElementById("signup-form").addEventListener("submit", async (e) => {
    e.preventDefault(); //don't leave the page
    const status = document.getElementById("su-status");

    const fd = new FormData(e.target); // sends username, password, password2
    const res = await fetch("http://127.0.0.1:8000/api/signup/", { method: "POST", body: fd });
    let data = {};
    try { data = await res.json(); } catch {}

    if (res.ok && data && data.id) {
        status.textContent = 'Account created: &{data.username} (id ${data.id})';
        status.style.color = "green";
        e.target.reset();
    } else {
        status.textContent = (data && data.error) ? data.error : 'signup failed (${res.status})';
        status.style.color = "crimson";
    }
});




// Passwords match/mismatch
const p1 = document.getElementById("su-password");
const p2 = document.getElementById("su-password2");
const psMsg = document.getElementById("pw-msg");
if (p1 && p2 && psMsg) {
    const check = () => {
        if (!p2.value){
            psMsg.textContent = ""; return;
        }
        psMsg.textContent = (p1.value === p2.value) ? "passwords match" : "passwords do not match";
    }
    p1.addEventListener("input", check);
    p2.addEventListener("input", check);
    console.log("password listeners attached");
}

//
// For Home.html

document.addEventListener("DOMContentLoaded", () => {
    const logoutBtn = document.getElementById("logout");
    if (!logoutBtn) return;
    logoutBtn.addEventListener("click", () => {
        localStorage.removeItem("mockCurrentUser");
        location.replace("login.html");
    })
})
  