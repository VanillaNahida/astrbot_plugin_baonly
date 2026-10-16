async (timeoutMs) => {
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const frames = (count) =>
    new Promise((resolve) => {
      const tick = () => (count-- > 0 ? requestAnimationFrame(tick) : resolve());
      tick();
    });
  const images = () => [...document.images];
  const pending = () => images().filter((img) => !img.complete);
  const scrollHeight = () => document.documentElement.scrollHeight;

  const step = Math.max(200, Math.floor(innerHeight * 0.75));
  for (let y = 0; y < scrollHeight(); y += step) {
    scrollTo({ top: y, behavior: "instant" });
    await pause(120);
  }
  scrollTo({ top: scrollHeight(), behavior: "instant" });
  images().forEach((img) => (img.loading = "eager"));

  const deadline = Date.now() + timeoutMs;
  while (pending().length && Date.now() < deadline) await pause(250);
  await Promise.all(images().filter((img) => img.naturalWidth).map((img) => img.decode().catch(() => {})));

  scrollTo({ top: 0, behavior: "instant" });
  document.activeElement?.blur?.();
  await document.fonts.ready;
  await pause(500);
  await frames(5);

  return {
    total: images().length,
    pending: pending().length,
    broken: images().filter((img) => img.complete && !img.naturalWidth).length,
  };
}
