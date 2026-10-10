"""Gera o site de verdade (server/app/static/site.html) a partir do desenho do Claude Design (landing.dc.html).

O desenho usa o formato do Claude Design (marcações {{...}}, <sc-if>, <sc-for> e a classe Component). Aqui ele vira
uma página comum: o mesmo HTML e a mesma lógica, com um mini motor próprio (abaixo, ~100 linhas) que desenha a
página e só troca o que mudou (as animações e o campo de e-mail não reiniciam a cada segundo).

Uso: python site/build_site.py   (rode depois de mexer no landing.dc.html; o servidor serve o arquivo gerado)
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "landing.dc.html")
OUT = os.path.join(HERE, "..", "server", "app", "static", "site.html")

RUNTIME = r"""
(function () {
  var HOLE = /\{\{\s*([^}]+?)\s*\}\}/g;
  function look(scope, path) {
    if (path === "true") return true; if (path === "false") return false;
    if (/^-?\d+(\.\d+)?$/.test(path)) return Number(path);
    var parts = path.split("."), v = scope;
    for (var i = 0; i < parts.length; i++) { if (v == null) return undefined; v = v[parts[i]]; }
    return v;
  }
  function whole(s) { var m = /^\s*\{\{\s*([^}]+?)\s*\}\}\s*$/.exec(s || ""); return m ? m[1] : null; }
  function interp(s, scope) { return s.replace(HOLE, function (_, p) { var v = look(scope, p); return v == null ? "" : String(v); }); }
  function build(node, scope, out) {
    if (node.nodeType === 3) { out.push(document.createTextNode(interp(node.data, scope))); return; }
    if (node.nodeType !== 1) return;
    var tag = node.localName;
    if (tag === "sc-if") {
      if (look(scope, whole(node.getAttribute("value")) || "")) kids(node, scope, out);
      return;
    }
    if (tag === "sc-for") {
      var list = look(scope, whole(node.getAttribute("list")) || "") || [], as = node.getAttribute("as") || "item";
      for (var i = 0; i < list.length; i++) { var s = Object.create(scope); s[as] = list[i]; s.$index = i; kids(node, s, out); }
      return;
    }
    var el = node.cloneNode(false); el.__on = {};
    for (var a = node.attributes.length - 1; a >= 0; a--) {
      var at = node.attributes[a], name = at.name, val = at.value;
      if (name.indexOf("hint-") === 0) { el.removeAttribute(name); continue; }
      if (name.indexOf("on") === 0 && whole(val)) { el.removeAttribute(name); el.__on[name.slice(2)] = look(scope, whole(val)); continue; }
      if (val.indexOf("{{") >= 0) el.setAttribute(name, interp(val, scope));
    }
    var c = []; kids(node, scope, c); for (var k = 0; k < c.length; k++) el.appendChild(c[k]);
    out.push(el);
  }
  function kids(node, scope, out) { for (var n = node.firstChild; n; n = n.nextSibling) build(n, scope, out); }
  function bind(el) {
    el.__bound = el.__bound || {};
    for (var ev in el.__on) if (!el.__bound[ev]) {
      el.__bound[ev] = true;
      (function (type) { el.addEventListener(type, function (e) { var f = el.__on && el.__on[type]; if (f) f(e); }); })(ev);
    }
  }
  function patch(parent, next) {
    var old = parent.childNodes;
    for (var i = 0; i < next.length; i++) {
      var n = next[i], o = old[i];
      if (!o) { parent.appendChild(n); walkBind(n); continue; }
      if (o.nodeType !== n.nodeType || o.nodeName !== n.nodeName) { parent.replaceChild(n, o); walkBind(n); continue; }
      if (n.nodeType === 3) { if (o.data !== n.data) o.data = n.data; continue; }
      for (var a = o.attributes.length - 1; a >= 0; a--) { var nm = o.attributes[a].name; if (!n.hasAttribute(nm)) o.removeAttribute(nm); }
      for (var b = 0; b < n.attributes.length; b++) { var at = n.attributes[b]; if (o.getAttribute(at.name) !== at.value) o.setAttribute(at.name, at.value); }
      o.__on = n.__on; bind(o);
      patch(o, Array.prototype.slice.call(n.childNodes));
    }
    while (old.length > next.length) parent.removeChild(parent.lastChild);
  }
  function walkBind(n) { if (n.nodeType !== 1) return; if (n.__on) bind(n); for (var c = n.firstChild; c; c = c.nextSibling) walkBind(c); }
  var pending = false, comp = null, root = null, tpl = null;
  function render() {
    pending = false;
    var out = []; kids(tpl.content, comp.renderVals(), out);
    patch(root, out);
  }
  window.DCLogic = function (props) { this.props = props || {}; this.state = {}; };
  window.DCLogic.prototype.setState = function (p) {
    Object.assign(this.state, typeof p === "function" ? p(this.state) : p);
    if (!pending) { pending = true; (window.requestAnimationFrame || setTimeout)(render); }
  };
  window.DCLogic.prototype.forceUpdate = function () { this.setState({}); };
  window.__mount = function (Cls, props) {
    tpl = document.getElementById("tpl"); root = document.getElementById("app");
    comp = new Cls(props); render(); if (comp.componentDidMount) comp.componentDidMount();
  };
})();
"""


def main() -> None:
    src = open(SRC, encoding="utf-8").read()
    helmet = re.search(r"<helmet>(.*?)</helmet>", src, re.S).group(1)
    body = re.search(r"<x-dc>(.*?)</x-dc>", src, re.S).group(1)
    body = re.sub(r"<helmet>.*?</helmet>", "", body, flags=re.S)
    logic = re.search(r"<script type=\"text/x-dc\"[^>]*>(.*?)</script>", src, re.S).group(1)

    # dados reais da empresa e links que o desenho deixou para preencher
    for ph in ("[EMPRESA LTD]", "[COMPANY LTD]", "[AZIENDA LTD]", "[FIRMA LTD]", "[SOCIÉTÉ LTD]", "[SYARIKAT LTD]"):
        logic = logic.replace(ph, "Fidus Labs Limited")
    body = body.replace('href="mailto:[CONTATO]"', 'href="mailto:suporte@heyfidus.com"')
    body = body.replace('<a href="#perguntas" style="color: #8D98A8">{{t.privacy}}</a>',
                        '<a href="/privacy?lang={{x.lang}}" style="color: #8D98A8">{{t.privacy}}</a>')
    body = body.replace('<a href="#perguntas" style="color: #8D98A8">{{t.terms}}</a>',
                        '<a href="/terms?lang={{x.lang}}" style="color: #8D98A8">{{t.terms}}</a>')
    # lista de espera: grava no servidor (antes era só demonstração)
    logic = logic.replace(
        "join: function (e) { if (e && e.preventDefault) e.preventDefault(); self.setState({ joined: true }); }",
        "join: function (e) { if (e && e.preventDefault) e.preventDefault(); var f = e && e.target; "
        "var em = f && f.querySelector ? (f.querySelector('input[type=email]') || {}).value : ''; "
        "try { fetch('/v1/site/waitlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, "
        "body: JSON.stringify({ email: em || '', lang: lang, platform: self.state.platform }) }); } catch (x) {} "
        "self.setState({ joined: true }); }")
    logic = logic.replace("x: { toast2s: f(T.toast2s),", "x: { lang: lang, toast2s: f(T.toast2s),")

    html = f"""<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fidus · Fale. O Fidus resolve.</title>
<meta name="description" content="Fidus: assessor pessoal por voz. Agenda, e-mails, gastos e pagamentos, falando. Fidus Labs Limited, Reino Unido.">
<meta property="og:title" content="Fidus · Fale. O Fidus resolve.">
<meta property="og:description" content="Assessor pessoal por voz para quem vive entre empresas, países e moedas.">
<meta name="theme-color" content="#07090D">
{helmet}
</head>
<body>
<div id="app"></div>
<template id="tpl">{body}</template>
<!-- gerado por site/build_site.py a partir de site/landing.dc.html: edite o desenho, não este arquivo -->
<script>{RUNTIME}</script>
<script>
{logic}
__mount(Component, {{ playStoreUrl: "__PLAY_URL__", appStoreUrl: "__APP_STORE_URL__" }});
</script>
</body>
</html>
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    print("site gerado:", os.path.relpath(OUT, os.path.join(HERE, "..")), f"({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
