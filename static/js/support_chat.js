(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function initSupportChat() {
    const root = document.querySelector("[data-support-chat]");
    if (!root || root.dataset.bound === "true") {
      return;
    }
    root.dataset.bound = "true";

    const toggle = root.querySelector("[data-support-chat-open]");
    const closeButton = root.querySelector("[data-support-chat-close]");
    const panel = root.querySelector(".support-chat__panel");
    const messagesEl = root.querySelector("[data-support-chat-messages]");
    const emptyState = root.querySelector("[data-support-chat-empty]");
    const codeEl = root.querySelector("[data-support-chat-code]");
    const form = root.querySelector("[data-support-chat-form]");
    const input = root.querySelector("[data-support-chat-input]");
    const statusEl = root.querySelector("[data-support-chat-status]");
    const intervalMs = Number(root.dataset.pollIntervalMs || 5000);
    let lastMessageId = 0;
    let pollTimer = null;
    let isLoading = false;
    let isSending = false;

    function setStatus(text, isError) {
      statusEl.textContent = text || "";
      statusEl.classList.toggle("is-error", Boolean(isError && text));
    }

    function updateConversationCode(code) {
      const value = String(code || "").trim();
      if (!value) {
        codeEl.hidden = true;
        codeEl.textContent = "";
        return;
      }
      codeEl.hidden = false;
      codeEl.textContent = value;
    }

    function scrollToBottom() {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function ensureEmptyState() {
      const hasMessages = Boolean(messagesEl.querySelector("[data-support-chat-message-id]"));
      emptyState.hidden = hasMessages;
    }

    function renderMessage(message) {
      const messageId = Number(message.id || 0);
      if (messageId && messagesEl.querySelector(`[data-support-chat-message-id="${messageId}"]`)) {
        return;
      }

      const item = document.createElement("div");
      item.className = `support-chat__message is-${message.sender_type || "system"}`;
      if (messageId) {
        item.dataset.supportChatMessageId = String(messageId);
        lastMessageId = Math.max(lastMessageId, messageId);
      }

      const bubble = document.createElement("div");
      bubble.className = "support-chat__bubble";
      bubble.textContent = message.body || "";
      item.appendChild(bubble);
      messagesEl.appendChild(item);
      ensureEmptyState();
    }

    function applyPayload(payload) {
      updateConversationCode(payload.conversation_code || "");
      (payload.messages || []).forEach(renderMessage);
      ensureEmptyState();
      if ((payload.messages || []).length) {
        scrollToBottom();
      }
    }

    async function loadMessages() {
      if (isLoading) {
        return;
      }
      isLoading = true;
      try {
        const url = new URL(root.dataset.messagesUrl, window.location.origin);
        if (lastMessageId > 0) {
          url.searchParams.set("after_id", String(lastMessageId));
        }
        const response = await fetch(url, {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error("load_failed");
        }
        applyPayload(await response.json());
      } catch (error) {
        setStatus("Could not refresh messages.", true);
      } finally {
        isLoading = false;
      }
    }

    async function submitMessage() {
      const message = input.value.trim();
      if (!message || isSending) {
        return;
      }
      isSending = true;
      setStatus("Sending...", false);
      try {
        const response = await fetch(root.dataset.sendUrl, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken"),
          },
          credentials: "same-origin",
          body: JSON.stringify({
            message,
            page_url: window.location.href,
            page_title: document.title,
          }),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "send_failed");
        }
        input.value = "";
        applyPayload(payload);
        setStatus("", false);
      } catch (error) {
        setStatus("Could not send the message.", true);
      } finally {
        isSending = false;
      }
    }

    function stopPolling() {
      if (pollTimer) {
        window.clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function startPolling() {
      stopPolling();
      pollTimer = window.setInterval(loadMessages, Math.max(intervalMs, 2000));
    }

    function setOpen(open) {
      root.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      panel.setAttribute("aria-hidden", open ? "false" : "true");
      if (open) {
        loadMessages();
        startPolling();
        window.setTimeout(() => input.focus(), 50);
      } else {
        stopPolling();
        setStatus("", false);
      }
    }

    toggle.addEventListener("click", () => setOpen(true));
    closeButton.addEventListener("click", () => setOpen(false));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitMessage();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submitMessage();
      }
    });
    document.addEventListener("click", (event) => {
      if (root.classList.contains("is-open") && !root.contains(event.target)) {
        setOpen(false);
      }
    });
    window.addEventListener("beforeunload", stopPolling);

    loadMessages();
  }

  document.addEventListener("DOMContentLoaded", initSupportChat);
  document.addEventListener("htmx:afterSwap", initSupportChat);
})();
