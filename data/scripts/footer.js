([text, selector]) => {
  const footer = document.createElement("div");
  footer.style.cssText =
    "text-align:center;padding:12px 0;font-size:16px;color:#000000;border-top:1px solid #eee;margin-top:20px;";
  footer.textContent = text;
  (document.querySelector(selector) ?? document.body).appendChild(footer);
}
