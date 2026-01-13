function getCookie(name) {
  const cookieValue = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  if (!cookieValue) {
    return "";
  }
  return decodeURIComponent(cookieValue.split("=").slice(1).join("="));
}

function buildChoiceList(choices, selectedId) {
  return choices
    .map((choice) => {
      const checked = String(choice.id) === String(selectedId || "");
      return `
        <label class="list-group-item d-flex gap-2 align-items-start">
          <input class="form-check-input mt-1" type="radio" name="choice_id" value="${choice.id}" ${
            checked ? "checked" : ""
          } required>
          <span>${choice.text}</span>
        </label>
      `;
    })
    .join("");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

function sanitizeLanguage(text) {
  const value = String(text ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
  return value || "python";
}

function isTruthyParam(value) {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function getQuestionType(question) {
  const raw = String(question?.question_type ?? "")
    .trim()
    .toLowerCase();
  if (raw === "blockly" || raw === "scratch" || raw === "code") {
    return raw;
  }
  if (question?.blockly_payload) {
    return "blockly";
  }
  if (question?.scratchblocks_text) {
    return "scratch";
  }
  if (question?.code_text) {
    return "code";
  }
  return "blockly";
}

function getQuestionDifficulty(question) {
  const raw = String(question?.difficulty ?? "")
    .trim()
    .toLowerCase();
  if (raw === "easy" || raw === "medium" || raw === "hard") {
    return raw;
  }
  return "medium";
}

function shuffleArray(items) {
  const array = Array.isArray(items) ? items.slice() : [];
  for (let i = array.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [array[i], array[j]] = [array[j], array[i]];
  }
  return array;
}

function selectQuestions(allQuestions) {
  const params = new URLSearchParams(window.location.search);
  const desiredType = String(params.get("type") || "").trim().toLowerCase();
  const desiredDifficulty = String(params.get("difficulty") || "").trim().toLowerCase();

  const randomMode = isTruthyParam(params.get("random"));
  const shuffleMode = randomMode || isTruthyParam(params.get("shuffle"));

  const countRaw = String(params.get("count") || "").trim();
  let desiredCount = Number.parseInt(countRaw, 10);
  if (!Number.isFinite(desiredCount) || desiredCount <= 0) {
    desiredCount = null;
  }

  let selected = Array.isArray(allQuestions) ? allQuestions.slice() : [];
  if (desiredType) {
    selected = selected.filter((question) => getQuestionType(question) === desiredType);
  }
  if (desiredDifficulty) {
    selected = selected.filter(
      (question) => getQuestionDifficulty(question) === desiredDifficulty
    );
  }

  if (shuffleMode) {
    selected = shuffleArray(selected);
  }

  if (desiredCount != null) {
    selected = selected.slice(0, desiredCount);
  }

  return selected;
}

function showToast(message, icon) {
  if (!window.Swal) {
    return;
  }
  window.Swal.fire({
    toast: true,
    position: "top-end",
    showConfirmButton: false,
    timer: 2500,
    timerProgressBar: true,
    icon: icon || "info",
    title: message || ""
  });
}

function copyToClipboard(rawText) {
  const text = String(rawText ?? "");
  if (!text.trim()) {
    return Promise.reject(new Error("Nothing to copy."));
  }

  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }

  return new Promise((resolve, reject) => {
    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "readonly");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      textarea.style.top = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(textarea);
      if (!ok) {
        reject(new Error("Copy failed."));
        return;
      }
      resolve();
    } catch (error) {
      reject(error);
    }
  });
}

function renderQuestionStage(container, question, meta) {
  const payloadId = `blockly-client-${question.id}`;
  const scratchId = `scratchblocks-client-${question.id}`;
  const promptHtml = String(question.prompt || "")
    .split("\n")
    .map((line) => `<div>${escapeHtml(line)}</div>`)
    .join("");

  const hasBlockly = Boolean(question.blockly_payload);
  const hasScratch = Boolean(question.scratchblocks_text);
  const hasCode = Boolean(question.code_text);
  const codeLanguage = sanitizeLanguage(question.code_language);

  container.innerHTML = `
    <div class="card shadow-sm">
      <div class="card-body">
        <div class="d-flex flex-wrap align-items-start justify-content-between gap-2 mb-3">
          <div class="text-muted small">
            Question ${meta.index + 1} / ${meta.total}
          </div>
        </div>
        <div class="mb-3 blockly-quiz-prompt">${promptHtml}</div>

        ${hasBlockly ? `<script id="${payloadId}" type="application/json"></script>` : ""}
        ${
          hasBlockly
            ? `
              <div class="mb-3">
                <div class="blockly-preview border rounded" data-blockly-preview data-blockly-script-id="${payloadId}"></div>
              </div>
            `
            : ""
        }

        ${hasScratch ? `<script id="${scratchId}" type="application/json"></script>` : ""}
        ${
          hasScratch
            ? `
              <div class="mb-3 quiz-snippet">
                <div class="quiz-snippet-toolbar">
                  <button type="button" class="btn btn-outline-secondary btn-sm" data-quiz-copy="scratch">
                    Copy
                  </button>
                </div>
                <div class="scratchblocks-preview border rounded" data-scratchblocks-preview data-scratchblocks-script-id="${scratchId}"></div>
              </div>
            `
            : ""
        }

        ${
          hasCode
            ? `
              <div class="mb-3 quiz-snippet">
                <div class="quiz-snippet-toolbar">
                  <button type="button" class="btn btn-outline-secondary btn-sm" data-quiz-copy="code">
                    Copy
                  </button>
                </div>
                <pre class="code-preview"><code class="language-${codeLanguage}">${escapeHtml(
                  question.code_text || ""
                )}</code></pre>
              </div>
            `
            : ""
        }

        <form data-quiz-answer-form>
          <div class="list-group quiz-choice-list mb-3">
            ${buildChoiceList(question.choices || [], meta.selectedChoiceId)}
          </div>
          <div class="d-flex flex-wrap justify-content-end gap-2">
            <button type="submit" class="btn btn-primary">
              ${meta.index + 1 >= meta.total ? "Finish" : "Next"}
            </button>
          </div>
        </form>
      </div>
    </div>
  `;

  if (hasBlockly) {
    const script = container.querySelector(`#${payloadId}`);
    if (script) {
      let payloadValue = question.blockly_payload;
      if (question.blockly_payload_kind === "state") {
        try {
          payloadValue = JSON.parse(payloadValue);
        } catch (error) {
          payloadValue = question.blockly_payload;
        }
      }
      script.textContent = JSON.stringify(payloadValue ?? "");
    }
    if (window.BlocklyQuiz && typeof window.BlocklyQuiz.initPreviews === "function") {
      window.BlocklyQuiz.initPreviews(container);
    }
  }

  if (hasScratch) {
    const script = container.querySelector(`#${scratchId}`);
    if (script) {
      script.textContent = JSON.stringify(String(question.scratchblocks_text ?? ""));
    }
    if (
      window.ScratchblocksQuiz &&
      typeof window.ScratchblocksQuiz.initPreviews === "function"
    ) {
      window.ScratchblocksQuiz.initPreviews(container);
    }
  }

  container.querySelector("[data-quiz-copy='scratch']")?.addEventListener("click", () => {
    copyToClipboard(question.scratchblocks_text || "")
      .then(() => showToast("Copied.", "success"))
      .catch(() => showToast("Copy failed.", "error"));
  });

  container.querySelector("[data-quiz-copy='code']")?.addEventListener("click", () => {
    copyToClipboard(question.code_text || "")
      .then(() => showToast("Copied.", "success"))
      .catch(() => showToast("Copy failed.", "error"));
  });
}

async function fetchJson(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

async function postJson(url, payload) {
  const csrfToken = getCookie("csrftoken");
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken
    },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = data?.error || `HTTP ${response.status}`;
    throw new Error(error);
  }
  return data;
}

function updateProgress(root, index, total) {
  const progressText = root.querySelector("[data-quiz-progress-text]");
  const progressBar = root.querySelector("[data-quiz-progress-bar]");
  const percent = total ? Math.round((index / total) * 100) : 0;
  if (progressText) {
    progressText.textContent = `${index} / ${total} answered`;
  }
  if (progressBar) {
    progressBar.style.width = `${percent}%`;
    progressBar.parentElement?.setAttribute("aria-valuenow", String(percent));
  }
}

function showError(container, message) {
  container.innerHTML = `
    <div class="alert alert-danger mb-0">
      ${escapeHtml(message || "Something went wrong.")}
    </div>
  `;
}

document.addEventListener("DOMContentLoaded", async () => {
  const root = document.querySelector("[data-quiz-play]");
  if (!root) {
    return;
  }

  const intro = root.querySelector("[data-quiz-intro]");
  const introToggle = root.querySelector("[data-quiz-toggle-intro]");
  const setIntroHidden = (hidden) => {
    if (!intro) {
      return;
    }
    if (hidden) {
      intro.classList.add("is-hidden");
    } else {
      intro.classList.remove("is-hidden");
    }
  };

  if (intro && introToggle) {
    introToggle.addEventListener("click", () => {
      setIntroHidden(intro.classList.contains("is-hidden") === false);
    });
  }

  const stage = root.querySelector("#quiz-client-stage");
  if (!stage) {
    return;
  }

  const apiQuizUrl = root.dataset.apiQuizUrl;
  const apiSubmitUrl = root.dataset.apiSubmitUrl;
  if (!apiQuizUrl || !apiSubmitUrl) {
    showError(stage, "Missing quiz API URLs.");
    return;
  }

  try {
    const payload = await fetchJson(apiQuizUrl);
    const allQuestions = Array.isArray(payload?.questions) ? payload.questions : [];
    const questions = selectQuestions(allQuestions);
    if (!questions.length) {
      showError(
        stage,
        allQuestions.length ? "No questions match your filters." : "This quiz has no questions yet."
      );
      return;
    }

    const answers = new Map();
    let index = 0;

    const nameInput = root.querySelector("#quiz-play-name");
    const dobInput = root.querySelector("#quiz-play-dob");
    const campusInput = root.querySelector("#quiz-play-campus");

    const render = () => {
      const current = questions[index];
      const selectedChoiceId = answers.get(current.id);
      renderQuestionStage(stage, current, {
        index,
        total: questions.length,
        selectedChoiceId
      });
      updateProgress(root, answers.size, questions.length);

      const form = stage.querySelector("[data-quiz-answer-form]");
      if (!form) {
        return;
      }
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const choiceInput = form.querySelector("input[name='choice_id']:checked");
        if (!choiceInput) {
          if (window.Swal) {
            window.Swal.fire({
              icon: "warning",
              title: "Please choose an answer."
            });
          }
          return;
        }
        answers.set(current.id, choiceInput.value);
        setIntroHidden(true);

        if (index + 1 < questions.length) {
          index += 1;
          render();
          return;
        }

        updateProgress(root, answers.size, questions.length);
        const submitPayload = {
          name: nameInput?.value || "",
          dob: dobInput?.value || "",
          campus: campusInput?.value || "",
          answers: Array.from(answers.entries()).map(([question_id, choice_id]) => ({
            question_id,
            choice_id
          }))
        };

        try {
          if (window.Swal) {
            window.Swal.fire({
              title: "Submitting...",
              allowOutsideClick: false,
              didOpen: () => window.Swal.showLoading()
            });
          }
          const result = await postJson(apiSubmitUrl, submitPayload);
          const reviewUrl = result?.review_url;
          if (reviewUrl) {
            window.location.assign(reviewUrl);
            return;
          }
          showError(stage, "Submitted, but no review URL returned.");
        } catch (error) {
          showError(stage, `Submit failed: ${error?.message || error}`);
        } finally {
          if (window.Swal) {
            window.Swal.close();
          }
        }
      });
    };

    render();
  } catch (error) {
    showError(stage, `Failed to load quiz: ${error?.message || error}`);
  }
});
