const root = document.documentElement;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const header = document.querySelector("[data-header]");

if (header) {
  const onScroll = () => header.classList.toggle("is-scrolled", window.scrollY > 12);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

const toggle = document.querySelector(".nav-toggle");
const nav = document.querySelector("#site-nav");

if (toggle && nav) {
  const label = toggle.querySelector(".nav-toggle-label");
  const setOpen = (open) => {
    toggle.setAttribute("aria-expanded", String(open));
    if (label) label.textContent = open ? "Close" : "Menu";
    nav.classList.toggle("is-open", open);
    if (header) header.classList.toggle("is-open", open);
  };

  toggle.addEventListener("click", () => {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  nav.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => setOpen(false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });

  window.matchMedia("(min-width: 900px)").addEventListener("change", (event) => {
    if (event.matches) setOpen(false);
  });
}

if ("IntersectionObserver" in window && !reduceMotion.matches) {
  const revealed = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-in");
      revealed.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });

  root.classList.add("reveal-on");
  document.querySelectorAll("[data-reveal]").forEach((el) => revealed.observe(el));
}

// Videos play only while on screen, and never on their own with reduced motion.
document.querySelectorAll("[data-video]").forEach((box) => {
  const video = box.querySelector("video");
  const button = box.querySelector("[data-video-toggle]");
  if (!video) return;

  let wanted = !reduceMotion.matches;
  let visible = false;

  const sync = () => {
    if (wanted && visible && !document.hidden) {
      const playing = video.play();
      if (playing) playing.catch(() => {});
    } else {
      video.pause();
    }
    if (button) button.textContent = wanted ? "Pause" : "Play";
  };

  if (button) {
    button.addEventListener("click", () => {
      wanted = !wanted;
      sync();
    });
  }

  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      sync();
    }, { threshold: 0.2 }).observe(box);
  } else {
    visible = true;
  }

  document.addEventListener("visibilitychange", sync);
  sync();
});

document.querySelectorAll("[data-marquee-toggle]").forEach((button) => {
  const target = document.getElementById(button.getAttribute("aria-controls"));
  button.addEventListener("click", () => {
    const paused = !(target && target.classList.contains("is-paused"));
    if (target) target.classList.toggle("is-paused", paused);
    button.textContent = paused ? "Play motion" : "Pause motion";
  });
});

const arenas = document.querySelector("[data-arenas]");

if (arenas) {
  const buttons = arenas.querySelectorAll("[data-arena-mode]");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const mode = button.dataset.arenaMode;
      arenas.dataset.mode = mode;
      buttons.forEach((other) => other.setAttribute("aria-pressed", String(other === button)));
      arenas.querySelectorAll(".arena-img img").forEach((img) => {
        const shown = img.classList.contains("undead") === (mode === "undead");
        img.setAttribute("aria-hidden", String(!shown));
      });
    });
  });
}
