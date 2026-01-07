function applyStagger(root) {
  const cards = root.querySelectorAll("[data-stagger]");
  cards.forEach((card, index) => {
    const custom = parseInt(card.dataset.stagger, 10);
    const delay = Number.isNaN(custom) ? index : custom;
    card.style.animationDelay = `${delay * 70}ms`;
  });
}

function getAuthModal() {
  return document.getElementById("auth-modal");
}

function openAuthModal() {
  const modal = getAuthModal();
  if (modal && !modal.open) {
    modal.showModal();
  }
}

function closeAuthModal() {
  const modal = getAuthModal();
  if (modal && modal.open) {
    modal.close();
  }
}

function getContactModal() {
  return document.getElementById("contact-modal");
}

function getPointsModal() {
  return document.getElementById("points-modal");
}

function getOwnerModal() {
  return document.getElementById("owner-modal");
}

function openContactModal() {
  const modal = getContactModal();
  if (modal && !modal.open) {
    modal.showModal();
  }
}

function openPointsModal() {
  const modal = getPointsModal();
  if (modal && !modal.open) {
    modal.showModal();
  }
}

function openOwnerModal() {
  const modal = getOwnerModal();
  if (modal && !modal.open) {
    modal.showModal();
  }
}

function closeOwnerModal() {
  const modal = getOwnerModal();
  if (modal && modal.open) {
    modal.close();
  }
}

function closeContactModal() {
  const modal = getContactModal();
  if (modal && modal.open) {
    modal.close();
  }
}

function resolveAlertIcon(tags) {
  if (!tags) {
    return "info";
  }
  const iconMap = {
    success: "success",
    error: "error",
    warning: "warning",
    info: "info",
    debug: "info"
  };
  const candidates = String(tags).split(/\s+/);
  for (const tag of candidates) {
    if (iconMap[tag]) {
      return iconMap[tag];
    }
  }
  return "info";
}

let lastNotifyKey = "";
let lastNotifyAt = 0;

function normalizeAlertMessage(entry) {
  if (!entry) {
    return null;
  }
  if (typeof entry === "string") {
    return { level: "info", text: entry };
  }
  if (entry.text) {
    return entry;
  }
  if (entry.message) {
    return { level: entry.level || entry.tags || "info", text: entry.message };
  }
  return entry;
}

async function showSweetAlerts(messages) {
  if (!window.Swal || !Array.isArray(messages) || messages.length === 0) {
    return;
  }
  const normalized = messages
    .map(normalizeAlertMessage)
    .filter((message) => message && String(message.text || "").trim().length > 0);
  if (!normalized.length) {
    return;
  }
  const key = JSON.stringify(normalized);
  const now = Date.now();
  if (key === lastNotifyKey && now - lastNotifyAt < 800) {
    return;
  }
  lastNotifyKey = key;
  lastNotifyAt = now;
  const toast = window.Swal.mixin({
    toast: true,
    position: "top-end",
    showConfirmButton: false,
    timer: 3500,
    timerProgressBar: true
  });
  for (const message of normalized) {
    await toast.fire({
      icon: resolveAlertIcon(message.level),
      title: message.text || ""
    });
  }
}

function parseTriggerPayload(value) {
  if (!value) {
    return null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return null;
    }
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try {
        return JSON.parse(trimmed);
      } catch (error) {
        return trimmed;
      }
    }
    return trimmed;
  }
  return value;
}

function extractNotifyMessages(payload) {
  if (!payload) {
    return null;
  }
  if (payload.notify) {
    return payload.notify;
  }
  if (payload.messages) {
    return payload.messages;
  }
  return payload;
}

function handleNotifyEvent(event) {
  let detail = event.detail;
  if (!detail) {
    return;
  }
  detail = parseTriggerPayload(detail);
  detail = extractNotifyMessages(detail);
  const messages = Array.isArray(detail) ? detail : [detail];
  showSweetAlerts(messages);
}

document.addEventListener("notify", handleNotifyEvent, true);
if (document.body) {
  document.body.addEventListener("notify", handleNotifyEvent, true);
}

function handleHtmxTriggerHeaders(xhr) {
  if (!xhr || typeof xhr.getResponseHeader !== "function") {
    return;
  }
  const headers = [
    xhr.getResponseHeader("HX-Trigger"),
    xhr.getResponseHeader("HX-Trigger-After-Swap"),
    xhr.getResponseHeader("HX-Trigger-After-Settle")
  ];
  headers.forEach((headerValue) => {
    const payload = parseTriggerPayload(headerValue);
    const notifyPayload = extractNotifyMessages(payload);
    if (!notifyPayload) {
      return;
    }
    const messages = Array.isArray(notifyPayload) ? notifyPayload : [notifyPayload];
    showSweetAlerts(messages);
  });
}

function bindBackdropClose(modal) {
  if (!modal) {
    return;
  }

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      modal.close();
    }
  });
}

function bindModalEvents() {
  bindBackdropClose(getAuthModal());
  bindBackdropClose(getContactModal());
  bindBackdropClose(getPointsModal());
  bindBackdropClose(getOwnerModal());
}

function bindContactTriggers() {
  const triggers = document.querySelectorAll("[data-contact-modal-open]");
  if (!triggers.length) {
    return;
  }
  triggers.forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      const modal = getContactModal();
      if (!modal) {
        return;
      }
      event.preventDefault();
      openContactModal();
    });
  });
}

function bindPointsTriggers() {
  const triggers = document.querySelectorAll("[data-points-modal-open]");
  if (!triggers.length) {
    return;
  }
  triggers.forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      const modal = getPointsModal();
      if (!modal) {
        return;
      }
      event.preventDefault();
      openPointsModal();
    });
  });
}

function normalizeUrl(value) {
  const url = String(value || "").trim();
  if (!url) {
    return "";
  }
  if (/^https?:\/\//i.test(url)) {
    return url;
  }
  return `https://${url}`;
}

function getLinkLabel(url) {
  let hostname = "";
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch (error) {
    hostname = url.toLowerCase();
  }
  if (hostname.includes("facebook.com") || hostname.includes("fb.com")) {
    return "Facebook";
  }
  if (hostname.includes("github.com")) {
    return "GitHub";
  }
  if (hostname.includes("tiktok.com")) {
    return "TikTok";
  }
  if (hostname.includes("youtube.com") || hostname.includes("youtu.be")) {
    return "YouTube";
  }
  if (hostname.includes("instagram.com")) {
    return "Instagram";
  }
  if (hostname.includes("twitter.com") || hostname.includes("x.com")) {
    return "Twitter";
  }
  if (hostname.includes("linkedin.com")) {
    return "LinkedIn";
  }
  if (hostname.includes("behance.net")) {
    return "Behance";
  }
  if (hostname.includes("dribbble.com")) {
    return "Dribbble";
  }
  return "Website";
}

let ownerModalTimer = null;

function cancelOwnerModalOpen() {
  if (ownerModalTimer) {
    window.clearTimeout(ownerModalTimer);
    ownerModalTimer = null;
  }
}

function scheduleOwnerModalOpen(callback) {
  cancelOwnerModalOpen();
  ownerModalTimer = window.setTimeout(() => {
    ownerModalTimer = null;
    callback();
  }, 150);
}

function bindOwnerTriggers() {
  const modal = getOwnerModal();
  if (!modal) {
    return;
  }
  const nameEl = modal.querySelector("#owner-modal-name");
  const usernameEl = modal.querySelector("#owner-modal-username");
  const roleEl = modal.querySelector("#owner-modal-role");
  const bioEl = modal.querySelector("#owner-modal-bio");
  const avatarImg = modal.querySelector("#owner-modal-avatar-img");
  const avatarInitial = modal.querySelector("#owner-modal-avatar-initial");
  const linksWrap = modal.querySelector("#owner-modal-links");
  const linksEmpty = modal.querySelector("#owner-modal-links-empty");
  const triggers = document.querySelectorAll("[data-owner-modal-open]");
  if (!triggers.length) {
    return;
  }
  triggers.forEach((trigger) => {
    if (trigger.dataset.ownerBound === "true") {
      return;
    }
    trigger.dataset.ownerBound = "true";
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      const dataset = trigger.dataset;
      const payload = {
        name: dataset.ownerName || "",
        username: dataset.ownerUsername || "",
        avatar: dataset.ownerAvatar || "",
        role: dataset.ownerRole || "",
        bio: dataset.ownerBio || "",
        urls: [
          dataset.ownerWebsite,
          dataset.ownerFacebook,
          dataset.ownerGithub
        ]
      };
      scheduleOwnerModalOpen(() => {
        const name = payload.name;
        const username = payload.username;
        const avatar = payload.avatar;
        const role = payload.role;
        const bio = payload.bio;
      const urls = [
        payload.urls[0],
        payload.urls[1],
        payload.urls[2]
      ]
        .map(normalizeUrl)
        .filter(Boolean);
      const uniqueUrls = Array.from(new Set(urls));
      const fallbackName = modal.dataset.ownerNameEmpty || "User";
      const fallbackRole = modal.dataset.ownerRoleEmpty || "Community member";
      const fallbackBio = modal.dataset.ownerBioEmpty || "No bio yet.";
      const fallbackLinks = modal.dataset.ownerLinksEmpty || "No links yet.";

      if (nameEl) {
        nameEl.textContent = name || username || fallbackName;
      }
      if (usernameEl) {
        const showUsername = username && username !== name;
        usernameEl.textContent = showUsername ? `@${username}` : "";
        usernameEl.hidden = !showUsername;
      }
      if (roleEl) {
        roleEl.textContent = role || fallbackRole;
        roleEl.hidden = false;
      }
      if (bioEl) {
        bioEl.textContent = bio || fallbackBio;
        bioEl.hidden = false;
      }
      if (avatarImg && avatarInitial) {
        if (avatar) {
          avatarImg.src = avatar;
          avatarImg.hidden = false;
          avatarInitial.hidden = true;
        } else {
          const initialSource = name || username || fallbackName;
          avatarInitial.textContent = initialSource.trim().charAt(0).toUpperCase();
          avatarImg.removeAttribute("src");
          avatarImg.hidden = true;
          avatarInitial.hidden = false;
        }
      }
      if (linksWrap) {
        linksWrap.innerHTML = "";
        if (uniqueUrls.length) {
          uniqueUrls.forEach((url) => {
            const label = getLinkLabel(url);
            const linkEl = document.createElement("a");
            linkEl.className = "owner-modal-link";
            linkEl.href = url;
            linkEl.target = "_blank";
            linkEl.rel = "noopener noreferrer";
            linkEl.textContent = label;
            linkEl.title = url;
            linksWrap.appendChild(linkEl);
          });
        }
        if (linksEmpty) {
          linksEmpty.textContent = uniqueUrls.length ? "" : fallbackLinks;
          linksEmpty.hidden = uniqueUrls.length > 0;
        }
      }
        openOwnerModal();
      });
    });
  });
}

function bindBackButtons() {
  const buttons = document.querySelectorAll("[data-back-button]");
  if (!buttons.length) {
    return;
  }
  const isHome = window.location.pathname === "/" || window.location.pathname === "";
  const canGoBack = !isHome && (window.history.length > 1 || document.referrer);
  buttons.forEach((button) => {
    if (!canGoBack) {
      button.style.display = "none";
      return;
    }
    button.addEventListener("click", () => window.history.back());
  });
}

function bindLanguageSwitcher() {
  const select = document.querySelector("[data-lang-switcher]");
  if (!select || !select.form) {
    return;
  }
  select.addEventListener("change", () => {
    select.form.submit();
  });
}

let userMenuDocBound = false;

function setUserMenuOpen(menu, open) {
  menu.classList.toggle("is-open", open);
  const toggle = menu.querySelector("[data-user-menu-toggle]");
  if (toggle) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
}

function bindUserMenu() {
  const menus = document.querySelectorAll("[data-user-menu]");
  if (!menus.length) {
    return;
  }
  menus.forEach((menu) => {
    if (menu.dataset.userMenuBound === "true") {
      return;
    }
    const toggle = menu.querySelector("[data-user-menu-toggle]");
    const dropdown = menu.querySelector("[data-user-menu-dropdown]");
    if (!toggle || !dropdown) {
      return;
    }
    menu.dataset.userMenuBound = "true";
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      const isOpen = menu.classList.contains("is-open");
      setUserMenuOpen(menu, !isOpen);
    });
    dropdown.addEventListener("click", (event) => {
      const action = event.target.closest(".user-menu-link, button");
      if (action) {
        setUserMenuOpen(menu, false);
      }
    });
  });
  if (userMenuDocBound) {
    return;
  }
  userMenuDocBound = true;
  document.addEventListener("click", (event) => {
    document.querySelectorAll("[data-user-menu].is-open").forEach((menu) => {
      if (!menu.contains(event.target)) {
        setUserMenuOpen(menu, false);
      }
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.querySelectorAll("[data-user-menu].is-open").forEach((menu) => {
        setUserMenuOpen(menu, false);
      });
    }
  });
}

function bindNavToggle() {
  const header = document.querySelector("[data-site-header]");
  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-nav-panel]");
  if (!header || !toggle || !nav) {
    return;
  }
  if (toggle.dataset.bound === "true") {
    return;
  }
  toggle.dataset.bound = "true";
  header.dataset.navReady = "true";

  const setOpen = (open) => {
    header.classList.toggle("is-nav-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  };

  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    const isOpen = header.classList.contains("is-nav-open");
    setOpen(!isOpen);
  });

  nav.addEventListener("click", (event) => {
    const link = event.target.closest(".nav-link, .user-menu-link");
    if (link) {
      setOpen(false);
    }
  });

  document.addEventListener("click", (event) => {
    if (!header.contains(event.target)) {
      setOpen(false);
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 700) {
      setOpen(false);
    }
  });
}

function bindProfileMenu() {
  const menu = document.querySelector(".profile-menu-list");
  if (!menu || menu.dataset.profileMenuBound === "true") {
    return;
  }
  menu.dataset.profileMenuBound = "true";
  syncProfileMenuActive();
  menu.addEventListener("click", (event) => {
    const link = event.target.closest(".profile-menu-link");
    if (!link) {
      return;
    }
    menu.querySelectorAll(".profile-menu-link").forEach((item) => {
      item.classList.toggle("is-active", item === link);
    });
  });
}

function getProfileSectionFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return params.get("section") || "personal";
}

function syncProfileMenuActive() {
  const menu = document.querySelector(".profile-menu-list");
  if (!menu) {
    return;
  }
  const current = getProfileSectionFromUrl();
  menu.querySelectorAll(".profile-menu-link").forEach((link) => {
    let linkSection = "";
    try {
      const url = new URL(link.getAttribute("href"), window.location.origin);
      linkSection = url.searchParams.get("section") || "";
    } catch (error) {
      linkSection = "";
    }
    link.classList.toggle("is-active", linkSection === current);
  });
}

function bindRecapLibrary() {
  const root = document.querySelector("[data-recap-library]");
  if (!root || root.dataset.recapBound === "true") {
    return;
  }
  const dataScript = document.getElementById("recap-data");
  const yearsScript = document.getElementById("recap-years");
  if (!dataScript || !yearsScript) {
    return;
  }
  let recaps = [];
  let yearsByCompetition = {};
  try {
    recaps = JSON.parse(dataScript.textContent);
    yearsByCompetition = JSON.parse(yearsScript.textContent);
  } catch (error) {
    return;
  }

  const competitionSelect = root.querySelector("[data-recap-competition]");
  const yearSelect = root.querySelector("[data-recap-year]");
  const cards = Array.from(root.querySelectorAll("[data-recap-card]"));
  const frame = root.querySelector("[data-recap-frame]");
  const videoWrap = root.querySelector("[data-recap-video]");
  const placeholder = root.querySelector("[data-recap-placeholder]");
  const title = root.querySelector("[data-recap-title]");
  const summary = root.querySelector("[data-recap-summary]");
  const meta = root.querySelector("[data-recap-meta]");
  const watchWrapper = root.querySelector("[data-recap-watch-wrapper]");
  const watchLink = root.querySelector("[data-recap-watch]");
  const watchYouTube = root.dataset.watchYoutube || "Watch on YouTube";
  const watchTikTok = root.dataset.watchTiktok || "Watch on TikTok";
  if (!competitionSelect || !yearSelect) {
    return;
  }

  const findRecap = (competition, year) =>
    recaps.find(
      (item) =>
        item.competition === competition && String(item.year) === String(year)
    );

  const setActiveCard = (competition, year) => {
    cards.forEach((card) => {
      const match = card.dataset.competition === competition;
      card.hidden = !match;
      const isActive = match && card.dataset.year === String(year);
      card.classList.toggle("is-active", isActive);
    });
  };

  const setYearOptions = (competition, year) => {
    const years = yearsByCompetition[competition] || [];
    yearSelect.innerHTML = years
      .map((value) => `<option value="${value}">${value}</option>`)
      .join("");
    if (year && years.includes(Number(year))) {
      yearSelect.value = String(year);
    } else if (years.length) {
      yearSelect.value = String(years[0]);
    }
  };

  const updatePlayer = (recap) => {
    if (!recap) {
      if (frame) {
        frame.hidden = true;
        frame.removeAttribute("src");
      }
      if (videoWrap) {
        videoWrap.dataset.provider = "";
      }
      if (placeholder) {
        placeholder.hidden = false;
      }
      if (title) {
        title.textContent = "";
      }
      if (summary) {
        summary.textContent = "";
      }
      if (meta) {
        meta.textContent = "";
      }
      if (watchWrapper) {
        watchWrapper.hidden = true;
      }
      if (watchLink) {
        watchLink.removeAttribute("href");
      }
      return;
    }
    if (recap.video_embed_url) {
      if (frame) {
        frame.hidden = false;
        frame.setAttribute(
          "src",
          recap.video_embed_url
        );
      }
      if (placeholder) {
        placeholder.hidden = true;
      }
    } else {
      if (frame) {
        frame.hidden = true;
        frame.removeAttribute("src");
      }
      if (placeholder) {
        placeholder.hidden = false;
      }
    }
    if (videoWrap) {
      videoWrap.dataset.provider = recap.video_provider || "";
    }
    if (title) {
      title.textContent = recap.title || "";
    }
    if (summary) {
      summary.textContent = recap.summary || "";
    }
    if (meta) {
      meta.textContent = `${recap.competition_label} - ${recap.year}`;
    }
    if (watchWrapper && watchLink && recap.video_watch_url) {
      watchWrapper.hidden = false;
      watchLink.href = recap.video_watch_url;
      watchLink.textContent =
        recap.video_provider === "TIKTOK" ? watchTikTok : watchYouTube;
    } else if (watchWrapper) {
      watchWrapper.hidden = true;
    }
  };

  const syncSelection = (competition, year) => {
    if (competitionSelect.value !== competition) {
      competitionSelect.value = competition;
    }
    setYearOptions(competition, year);
    const recap = findRecap(competition, yearSelect.value);
    setActiveCard(competition, yearSelect.value);
    updatePlayer(recap);
  };

  competitionSelect.addEventListener("change", () => {
    syncSelection(competitionSelect.value, null);
  });

  yearSelect.addEventListener("change", () => {
    syncSelection(competitionSelect.value, yearSelect.value);
  });

  cards.forEach((card) => {
    card.addEventListener("click", () => {
      syncSelection(card.dataset.competition, card.dataset.year);
    });
  });

  syncSelection(competitionSelect.value, yearSelect.value);
  root.dataset.recapBound = "true";
}

function bindDownloadBanner() {
  const form = document.querySelector("[data-download-form]");
  const banner = document.getElementById("download-banner");
  if (!form || !banner) {
    return;
  }

  if (form.dataset.bannerBound === "true") {
    return;
  }
  form.dataset.bannerBound = "true";

  const continueButton = banner.querySelector("[data-download-banner-continue]");
  const closeButton = banner.querySelector("[data-download-banner-close]");
  const countdownLabel = banner.querySelector("[data-download-banner-countdown]");
  const countdownSeconds = 5;

  const openBanner = () => {
    banner.classList.add("download-banner--visible");
    banner.setAttribute("aria-hidden", "false");
    startCountdown();
  };

  const setContinueEnabled = (enabled) => {
    if (continueButton) {
      continueButton.disabled = !enabled;
    }
  };

  const setCountdownValue = (value) => {
    if (countdownLabel) {
      countdownLabel.textContent = String(value);
    }
  };

  let countdownTimer = null;
  const startCountdown = () => {
    let remaining = countdownSeconds;
    setCountdownValue(remaining);
    setContinueEnabled(false);
    if (countdownTimer) {
      window.clearInterval(countdownTimer);
    }
    countdownTimer = window.setInterval(() => {
      remaining -= 1;
      setCountdownValue(remaining);
      if (remaining <= 0) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
        setContinueEnabled(true);
      }
    }, 1000);
  };

  const closeBanner = () => {
    banner.classList.remove("download-banner--visible");
    banner.setAttribute("aria-hidden", "true");
    if (countdownTimer) {
      window.clearInterval(countdownTimer);
      countdownTimer = null;
    }
    setCountdownValue(countdownSeconds);
    setContinueEnabled(false);
  };

  let isSubmitting = false;
  const submitForm = () => {
    if (isSubmitting) {
      return;
    }
    isSubmitting = true;
    closeBanner();
    form.submit();
    window.setTimeout(() => {
      isSubmitting = false;
    }, 1000);
  };

  const parseNumber = (value) => {
    const parsed = Number.parseInt(String(value || ""), 10);
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const showToast = (level, text) => {
    if (!text) {
      return;
    }
    try {
      showSweetAlerts([{ level, text }]);
    } catch {
      // ignore
    }
  };

  form.addEventListener("submit", (event) => {
    if (isSubmitting) {
      event.preventDefault();
      return;
    }

    const unlocked = form.dataset.downloadUnlocked === "true";
    const cost = parseNumber(form.dataset.downloadCost);
    const points = parseNumber(form.dataset.userPoints);

    if (!unlocked && cost > 0 && points < cost) {
      event.preventDefault();
      showToast("error", form.dataset.downloadInsufficientMessage);
      return;
    }

    if (!unlocked) {
      isSubmitting = true;
      return;
    }

    event.preventDefault();
    openBanner();
  });

  if (continueButton) {
    continueButton.addEventListener("click", () => {
      if (continueButton.disabled) {
        return;
      }
      submitForm();
    });
  }
  if (closeButton) {
    closeButton.addEventListener("click", closeBanner);
  }

  banner.addEventListener("click", (event) => {
    if (event.target === banner) {
      closeBanner();
    }
  });

  if (banner.dataset.keyBound !== "true") {
    banner.dataset.keyBound = "true";
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeBanner();
      }
    });
  }
}

function bindPolicyTabs() {
  const root = document.querySelector("[data-policy-tabs]");
  if (!root || root.dataset.policyBound === "true") {
    return;
  }
  root.dataset.policyBound = "true";

  const tabs = Array.from(root.querySelectorAll("[data-policy-tab]"));
  const panels = Array.from(root.querySelectorAll("[data-policy-panel]"));
  if (!tabs.length || !panels.length) {
    return;
  }

  const setActive = (name, updateUrl) => {
    let found = false;
    tabs.forEach((tab) => {
      const active = tab.dataset.policyTab === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
      if (active) {
        found = true;
      }
    });
    panels.forEach((panel) => {
      const active = panel.dataset.policyPanel === name;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
    if (found && updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", name);
      window.history.replaceState({}, "", url);
    }
  };

  const params = new URLSearchParams(window.location.search);
  const initial = params.get("tab");
  const valid = tabs.some((tab) => tab.dataset.policyTab === initial);
  const defaultTab = tabs[0].dataset.policyTab;
  setActive(valid ? initial : defaultTab, false);

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      setActive(tab.dataset.policyTab, true);
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  applyStagger(document);
  bindModalEvents();
  bindContactTriggers();
  bindPointsTriggers();
  bindBackButtons();
  bindLanguageSwitcher();
  bindUserMenu();
  bindNavToggle();
  bindProfileMenu();
  bindRecapLibrary();
  bindDownloadBanner();
  bindPolicyTabs();
  bindOwnerTriggers();
  if (window.__djangoMessages) {
    showSweetAlerts(window.__djangoMessages);
  }
});

document.addEventListener("htmx:afterRequest", (event) => {
  const xhr = event.detail ? event.detail.xhr : null;
  if (xhr) {
    handleHtmxTriggerHeaders(xhr);
  }
});

document.addEventListener("htmx:afterSwap", (event) => {
  if (event.target) {
    applyStagger(event.target);
    if (event.target.id === "auth-modal-body") {
      openAuthModal();
    }
  }
  bindRecapLibrary();
  bindDownloadBanner();
  bindPointsTriggers();
  bindPolicyTabs();
  bindOwnerTriggers();
  bindNavToggle();
  bindUserMenu();
  bindProfileMenu();
  syncProfileMenuActive();
});

document.addEventListener("htmx:beforeRequest", (event) => {
  const target = event.detail ? event.detail.target : null;
  if (target && target.id === "auth-modal-body") {
    openAuthModal();
  }
  cancelOwnerModalOpen();
  closeOwnerModal();
});

document.addEventListener("click", (event) => {
  const closeButton = event.target.closest("[data-modal-close]");
  if (!closeButton) {
    if (!event.target.closest("[data-owner-modal-open]")) {
      cancelOwnerModalOpen();
    }
    return;
  }
  const dialog = closeButton.closest("dialog");
  if (dialog && dialog.open) {
    dialog.close();
    return;
  }
  closeAuthModal();
  closeContactModal();
  closeOwnerModal();
});

window.addEventListener("popstate", () => {
  cancelOwnerModalOpen();
  closeOwnerModal();
  syncProfileMenuActive();
});

window.addEventListener("beforeunload", () => {
  cancelOwnerModalOpen();
  closeOwnerModal();
});
