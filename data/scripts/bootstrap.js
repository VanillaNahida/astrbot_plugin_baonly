(pageSize) => {
  Object.defineProperty(navigator, "webdriver", { get: () => undefined });

  const seed = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch {}
  };
  const read = (key) => {
    try {
      return JSON.parse(localStorage.getItem(key) || "{}");
    } catch {
      return {};
    }
  };

  seed("baonly:tour:seen", JSON.stringify({ ...read("baonly:tour:seen"), client: new Date().toISOString() }));
  seed("baonly:page-size:v1", String(pageSize));
  seed(
    "baonly:prefs:v1",
    JSON.stringify({
      ...read("baonly:prefs:v1"),
      autoTier: false,
      tier: "full",
      autoHideBar: false,
      reveal: false,
      smoothScroll: false,
      edgeFade: false,
      hoverFocus: false,
      hoverBlur: false,
      clickBurst: false,
    }),
  );

  const getItem = Storage.prototype.getItem;
  Storage.prototype.getItem = function (key) {
    if (typeof key === "string" && key.startsWith("announcement-seen:")) return "1";
    return getItem.call(this, key);
  };
}
