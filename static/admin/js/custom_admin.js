function resolveAdminAlertIcon(tags) {
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

async function showAdminSweetAlerts(messages) {
  if (!window.Swal || !Array.isArray(messages) || messages.length === 0) {
    return;
  }
  document.body.classList.add("sweetalerts-enabled");
  const toast = window.Swal.mixin({
    toast: true,
    position: "top-end",
    showConfirmButton: false,
    timer: 3500,
    timerProgressBar: true
  });
  for (const message of messages) {
    await toast.fire({
      icon: resolveAdminAlertIcon(message.level),
      title: message.text || ""
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  if (window.__djangoMessages) {
    showAdminSweetAlerts(window.__djangoMessages);
  }
});
