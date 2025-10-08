from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render

def stocks_clean(request):
    csrf = get_token(request) or ""
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>STOCKS CLEAN</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body{background:#0b1020;color:#e5e7eb;font-family:system-ui;padding:24px}
    .tabs{display:flex;gap:12px;margin:12px 0 8px;border-bottom:1px solid rgba(255,255,255,.28)}
    .tab{color:#e5e7eb;text-decoration:none;padding:8px 12px;border-radius:10px 10px 0 0;border:1px solid transparent;border-bottom:none}
    .tab.active{background:rgba(255,255,255,.06);border-color:rgba(255,255,255,.28)}
    .toolbar{display:flex;justify-content:flex-end;gap:8px;padding-top:8px}
    input,button{padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.28);background:transparent;color:#e5e7eb}
  </style>
</head>
<body>
  <h1>STOCKS CLEAN</h1>
  <nav class="tabs">
    <a class="tab active" href="#today">Today</a>
    <a class="tab" href="#tickers">Tickers</a>
  </nav>

  <div class="toolbar">
    <form id="upd-form" autocomplete="off" method="post">
      <input type="hidden" name="csrfmiddlewaretoken" value="__CSRF__">
      <input id="upd-ticker" name="ticker" placeholder="AAPL"/>
      <button id="upd-btn" type="submit">Update</button>
      <span id="upd-status"></span>
    </form>
  </div>

  <script>
    console.log("✅ stocks_clean inline JS running");
    document.addEventListener('DOMContentLoaded', function(){
      var f = document.getElementById('upd-form');
      var t = document.getElementById('upd-ticker');
      var s = document.getElementById('upd-status');
      var b = document.getElementById('upd-btn');
      var csrf = f.querySelector('input[name=csrfmiddlewaretoken]').value;

      f.addEventListener('submit', async function(e){
        e.preventDefault();
        var ticker = (t.value || '').trim().toUpperCase();
        if (!ticker) { s.textContent = 'Enter ticker'; return; }
        b.disabled = true; s.textContent = 'Updating…';
        try {
          var fd = new FormData();
          fd.append('ticker', ticker);
          var res = await fetch('/api/today/update', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf },
            body: fd
          });
          var js = await res.json().catch(function(){ return {}; });
          if (res.ok && js.ok) {
            s.textContent = '✓ ' + js.ticker + ': +' + (js.rows_added || 0) + ' (total ' + (js.total_rows || '—') + ')';
          } else {
            s.textContent = (js && js.error) ? js.error : ('Error ' + res.status);
          }
        } catch (err) {
          s.textContent = String(err);
        } finally {
          b.disabled = false;
        }
      });
    });
  </script>
</body>
</html>
"""
    return HttpResponse(html.replace("__CSRF__", csrf))


def stocks_page(request):
    # Render a namespaced template so Django can’t pick the wrong one
    return render(request, "accounts/templates/today_stocks_clean.html")


def stocks_today(request):
    # This returns the HTML for the Today tab only (a fragment).
    # We’ll inject it into the main page via fetch().
    return render(request, "fragment_today_stocks.html")