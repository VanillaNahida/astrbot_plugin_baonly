(marker) => {
  const hide = (el) => el?.style.setProperty("display", "none", "important");
  const list = document.querySelector('[data-tour="list"]');
  const root = list?.parentElement;
  if (!root) return false;

  document.querySelectorAll(".island").forEach((island) => hide(island.closest(".fixed") ?? island));
  hide(document.querySelector('[data-tour="search"]')?.closest(".contents"));
  for (let el = list.nextElementSibling; el; el = el.nextElementSibling) hide(el);

  root.setAttribute(marker, "");
  return true;
}
