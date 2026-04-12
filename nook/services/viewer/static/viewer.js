function buildMarkdownRequestPath(appName, currentDate, previousUpdatedAt = null) {
  const query = new URLSearchParams({ date: currentDate });
  if (previousUpdatedAt) {
    query.set("previous_updated_at", previousUpdatedAt);
  }
  return `/api/markdown/${appName}?${query.toString()}`;
}

function buildRetryPollRequestOptions(markdownExists, markdownUpdatedAt) {
  return {
    preserveCurrentContentOn404: markdownExists,
    previousUpdatedAt: markdownUpdatedAt,
  };
}

function buildChatRequestPayload(articleId, currentDate, chatHistory, message) {
  return {
    article_id: articleId,
    date: currentDate,
    chat_history: chatHistory,
    message,
  };
}

function slugify(text, index) {
  const normalized = text
    .trim()
    .toLowerCase()
    .replace(/[^\w\u3040-\u30ff\u3400-\u9fff\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || `section-${index}`;
}

function resolveInitialApp(appNames) {
  return appNames[0] || null;
}

if (typeof window !== "undefined") {
  window.__myNookViewerTestHooks = {
    buildMarkdownRequestPath,
    buildRetryPollRequestOptions,
    buildChatRequestPayload,
    cloneArticles,
    cloneHeadings,
    flattenArticleHeadings,
    reconcileChatHistory,
    resolveInitialApp,
    slugify,
  };
}

function cloneHeadings(headings) {
  return headings.map((heading) => ({
    text: heading.text,
    anchor: heading.anchor,
    level: heading.level,
  }));
}

function cloneArticles(articles) {
  return articles.map((article) => ({
    article_id: article.article_id,
    title: article.title,
    html: article.html || "",
    headings: cloneHeadings(article.headings || []),
  }));
}

function cloneArticlesByApp(appNames, articlePayload) {
  return Object.fromEntries(
    appNames.map((appName) => [
      appName,
      cloneArticles(articlePayload[appName] || []),
    ]),
  );
}

function buildInitialChatHistory(appNames, articlePayload) {
  return Object.fromEntries(
    appNames.map((appName) => [
      appName,
      Object.fromEntries(
        (articlePayload[appName] || []).map((article) => [article.article_id, []]),
      ),
    ]),
  );
}

function reconcileChatHistory(currentHistory, articles) {
  return Object.fromEntries(
    articles.map((article) => [article.article_id, currentHistory[article.article_id] || []]),
  );
}

function flattenArticleHeadings(articles) {
  return articles.flatMap((article) => cloneHeadings(article.headings || []));
}

function bootstrapViewer() {
  const stateNode = document.getElementById("viewer-state");
  if (!stateNode) {
    return;
  }

  const initialState = JSON.parse(stateNode.textContent);
  const tabLabels = {
    tech_news: "News",
    tech_feed: "Feeds",
    product_hunt: "ProductHunt",
    hacker_news: "HN",
    github_trending: "GitHub",
    reddit_explorer: "Reddit",
    paper_summarizer: "Papers",
    google_alerts: "Alerts",
  };

  const runtime = {
    appNames: initialState.app_names,
    articles: cloneArticlesByApp(initialState.app_names, initialState.articles || {}),
    markdownExists: { ...initialState.markdown_exists },
    markdownUpdatedAt: { ...initialState.markdown_updated_at },
    weather: { ...initialState.weather_data },
    currentDate: initialState.date,
    currentApp: resolveInitialApp(initialState.app_names),
    chatHistory: buildInitialChatHistory(
      initialState.app_names,
      initialState.articles || {},
    ),
    pendingChatKeys: new Set(),
    pollTimerId: null,
  };

  const elements = {
    appNav: document.getElementById("app-nav"),
    articleContent: document.getElementById("article-content"),
    missingAlert: document.getElementById("missing-alert"),
    retryButton: document.getElementById("retry-button"),
    statusMessage: document.getElementById("status-message"),
    tocList: document.getElementById("toc-list"),
    dateForm: document.getElementById("date-form"),
    datePicker: document.getElementById("date"),
    weather: document.getElementById("weather"),
    clock: document.getElementById("clock"),
    scrollTopButton: document.getElementById("scrollTopBtn"),
  };

  function displayLabel(appName) {
    return tabLabels[appName] || appName;
  }

  function escapeHtml(value) {
    return value
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function escapeAttribute(value) {
    return escapeHtml(value)
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderMarkdown(markdown) {
    if (!window.marked || !window.DOMPurify) {
      return `<pre>${escapeHtml(markdown)}</pre>`;
    }

    const fallback = "Content not found.";
    const html = window.marked.parse(markdown || fallback, {
      breaks: true,
      gfm: true,
    });
    return window.DOMPurify.sanitize(html);
  }

  function articleChatKey(appName, articleId) {
    return `${appName}:${articleId}`;
  }

  function currentArticles(appName = runtime.currentApp) {
    if (!appName) {
      return [];
    }
    return runtime.articles[appName] || [];
  }

  function findArticle(appName, articleId) {
    return currentArticles(appName).find((article) => article.article_id === articleId);
  }

  function syncChatHistory(appName) {
    const currentHistory = runtime.chatHistory[appName] || {};
    runtime.chatHistory[appName] = reconcileChatHistory(
      currentHistory,
      currentArticles(appName),
    );
  }

  function serializeChatHistory(appName, articleId) {
    const messages = runtime.chatHistory[appName]?.[articleId] || [];
    if (messages.length === 0) {
      return "none";
    }
    return messages.map((message) => `${message.role}: ${message.content}`).join("\n\n");
  }

  function renderToc(headings) {
    elements.tocList.innerHTML = "";
    if (headings.length === 0) {
      elements.tocList.innerHTML =
        '<li class="toc-item"><span class="empty-state">No headings</span></li>';
      return;
    }

    headings.forEach((heading) => {
      const item = document.createElement("li");
      item.className = "toc-item";

      const link = document.createElement("a");
      link.className = "toc-link";
      link.href = `#${heading.anchor}`;
      link.dataset.level = String(heading.level);
      link.textContent = heading.text;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        elements.tocList
          .querySelectorAll(".toc-link")
          .forEach((node) => node.classList.remove("active"));
        link.classList.add("active");
        const target = document.getElementById(heading.anchor);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });

      item.appendChild(link);
      elements.tocList.appendChild(item);
    });
  }

  function renderNav() {
    elements.appNav.innerHTML = "";

    runtime.appNames.forEach((appName) => {
      const item = document.createElement("li");
      item.className = "nav-item";
      item.role = "presentation";

      const button = document.createElement("button");
      button.type = "button";
      button.role = "tab";
      button.className = "nav-link";
      button.dataset.appName = appName;
      if (appName === runtime.currentApp) {
        button.classList.add("active");
      }
      button.textContent = displayLabel(appName);
      button.addEventListener("click", () => {
        runtime.currentApp = appName;
        render();
      });

      item.appendChild(button);
      elements.appNav.appendChild(item);
    });
  }

  function renderChatLogHtml(appName, articleId) {
    const messages = runtime.chatHistory[appName]?.[articleId] || [];
    if (messages.length === 0) {
      return "";
    }

    return messages
      .map((message) => {
        if (message.role === "assistant") {
          return `
            <div class="chat-message assistant-message">
              <strong>Assistant:</strong>
              <div class="markdown-content">${renderMarkdown(message.content)}</div>
            </div>
          `;
        }
        return `
          <div class="chat-message user-message">
            <strong>You:</strong> ${escapeHtml(message.content)}
          </div>
        `;
      })
      .join("");
  }

  function renderArticleSection(appName, article) {
    const isPending = runtime.pendingChatKeys.has(
      articleChatKey(appName, article.article_id),
    );
    const articleId = escapeAttribute(article.article_id);
    const buttonLabel = isPending ? "Asking..." : "Ask";
    const disabledAttribute = isPending ? " disabled" : "";

    return `
      <section class="article-section" data-article-id="${articleId}">
        <div class="article-body markdown-content">${article.html}</div>
        <div class="chat-container article-chat-container">
          <div class="chat-log article-chat-log" data-article-id="${articleId}">
            ${renderChatLogHtml(appName, article.article_id)}
          </div>
          <form class="chat-input article-chat-form" data-article-id="${articleId}">
            <textarea
              class="form-control article-chat-input"
              data-article-id="${articleId}"
              placeholder="Ask a question about this article..."${disabledAttribute}
            ></textarea>
            <button
              type="submit"
              class="btn btn-primary article-chat-submit"${disabledAttribute}
            >${buttonLabel}</button>
          </form>
        </div>
      </section>
    `;
  }

  function renderArticle() {
    const appName = runtime.currentApp;
    if (!appName) {
      return;
    }

    syncChatHistory(appName);
    const articles = currentArticles(appName);
    const hasMarkdown = runtime.markdownExists[appName] && articles.length > 0;

    elements.missingAlert.classList.toggle("d-none", hasMarkdown);
    if (!hasMarkdown) {
      elements.missingAlert.textContent = `Content for ${runtime.currentDate} not found.`;
      elements.articleContent.innerHTML =
        '<p class="empty-state">Content for this date is not available.</p>';
      renderToc([]);
      return;
    }

    elements.articleContent.innerHTML = articles
      .map((article) => renderArticleSection(appName, article))
      .join("");

    const headings = flattenArticleHeadings(articles);
    renderToc(headings);
  }

  function renderWeather() {
    const temp = runtime.weather.temp || "--";
    const icon = runtime.weather.weather_icon || "";
    elements.weather.textContent = icon ? `${temp}°C ${icon}` : `${temp}°C`;
  }

  function renderClock() {
    elements.clock.textContent = new Intl.DateTimeFormat("ja-JP", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date());
  }

  function setStatus(message) {
    elements.statusMessage.textContent = message;
  }

  function updateScrollTopButton() {
    if (!elements.scrollTopButton) {
      return;
    }
    elements.scrollTopButton.style.display = window.scrollY > 200 ? "flex" : "none";
  }

  async function safeJson(response) {
    try {
      return await response.json();
    } catch {
      return {};
    }
  }

  async function refreshWeather() {
    try {
      const response = await fetch("/api/weather");
      if (!response.ok) {
        return;
      }
      runtime.weather = await response.json();
      renderWeather();
    } catch {}
  }

  async function loadMarkdown(appName, options = {}) {
    const preserveCurrentContentOn404 =
      options.preserveCurrentContentOn404 === true;
    const response = await fetch(
      buildMarkdownRequestPath(
        appName,
        runtime.currentDate,
        options.previousUpdatedAt || null,
      ),
    );

    if (response.status === 404) {
      if (!preserveCurrentContentOn404) {
        runtime.markdownExists[appName] = false;
        runtime.markdownUpdatedAt[appName] = null;
        runtime.articles[appName] = [];
        runtime.chatHistory[appName] = {};
      }
      return { found: false, updatedAt: null };
    }

    if (!response.ok) {
      throw new Error(`Failed to load markdown for ${appName}`);
    }

    const payload = await response.json();
    runtime.articles[appName] = cloneArticles(payload.articles || []);
    runtime.markdownExists[appName] = runtime.articles[appName].length > 0;
    runtime.markdownUpdatedAt[appName] = payload.updated_at || null;
    syncChatHistory(appName);
    return {
      found: runtime.articles[appName].length > 0,
      updatedAt: payload.updated_at || null,
    };
  }

  function stopPolling() {
    if (runtime.pollTimerId !== null) {
      window.clearInterval(runtime.pollTimerId);
      runtime.pollTimerId = null;
    }
  }

  function startPolling(appName) {
    stopPolling();
    let remainingAttempts = 24;
    const pollOptions = buildRetryPollRequestOptions(
      runtime.markdownExists[appName],
      runtime.markdownUpdatedAt[appName],
    );

    runtime.pollTimerId = window.setInterval(async () => {
      remainingAttempts -= 1;
      try {
        const result = await loadMarkdown(appName, pollOptions);
        if (result.found) {
          render();
          stopPolling();
          setStatus(`${displayLabel(appName)} updated.`);
        } else if (remainingAttempts <= 0) {
          stopPolling();
          setStatus("Retry accepted. Waiting for content.");
        }
      } catch {
        stopPolling();
        setStatus("Failed to check updated content.");
      }
    }, 5000);
  }

  async function retryCurrentApp() {
    const appName = runtime.currentApp;
    if (!appName) {
      return;
    }

    elements.retryButton.disabled = true;
    const originalText = elements.retryButton.textContent;
    elements.retryButton.textContent = "Triggering...";
    setStatus(`Retrying ${displayLabel(appName)}...`);

    try {
      const response = await fetch(`/retry/${appName}`, { method: "POST" });
      const payload = await safeJson(response);
      if (!response.ok) {
        throw new Error(payload.detail || "Retry failed");
      }
      startPolling(appName);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Retry failed.");
    } finally {
      window.setTimeout(() => {
        elements.retryButton.textContent = originalText;
        elements.retryButton.disabled = false;
      }, 1000);
    }
  }

  async function submitArticleChat(event) {
    const form = event.target.closest(".article-chat-form");
    if (!form) {
      return;
    }
    event.preventDefault();

    const appName = runtime.currentApp;
    if (!appName) {
      return;
    }

    const articleId = form.dataset.articleId;
    const article = findArticle(appName, articleId);
    const textarea = form.querySelector(".article-chat-input");
    if (!article || !textarea) {
      return;
    }

    const message = textarea.value.trim();
    if (!message) {
      return;
    }

    syncChatHistory(appName);
    const key = articleChatKey(appName, articleId);
    if (runtime.pendingChatKeys.has(key)) {
      return;
    }

    const priorChatHistory = serializeChatHistory(appName, articleId);
    runtime.chatHistory[appName][articleId].push({
      role: "user",
      content: message,
    });
    runtime.pendingChatKeys.add(key);
    setStatus(`Asking about ${article.title}...`);
    renderArticle();

    try {
      const response = await fetch(`/chat/${appName}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          buildChatRequestPayload(
            article.article_id,
            runtime.currentDate,
            priorChatHistory,
            message,
          ),
        ),
      });

      const payload = await safeJson(response);
      if (!response.ok) {
        throw new Error(payload.detail || "Chat failed");
      }

      runtime.chatHistory[appName][articleId].push({
        role: "assistant",
        content: payload.response || "No response",
      });
      setStatus("");
    } catch (error) {
      runtime.chatHistory[appName][articleId].push({
        role: "assistant",
        content: error instanceof Error ? error.message : "Failed to get response",
      });
      setStatus("Chat failed.");
    } finally {
      runtime.pendingChatKeys.delete(key);
      renderArticle();
    }
  }

  function handleDateSubmit(event) {
    event.preventDefault();
    const url = new URL(window.location.href);
    url.searchParams.set("date", elements.datePicker.value);
    window.location.href = url.toString();
  }

  function render() {
    renderNav();
    renderArticle();
    renderWeather();
    renderClock();
    elements.datePicker.value = runtime.currentDate;
  }

  elements.retryButton.addEventListener("click", retryCurrentApp);
  elements.dateForm.addEventListener("submit", handleDateSubmit);
  elements.articleContent.addEventListener("submit", submitArticleChat);
  if (elements.scrollTopButton) {
    elements.scrollTopButton.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }
  window.addEventListener("scroll", updateScrollTopButton);

  render();
  refreshWeather();
  updateScrollTopButton();
  window.setInterval(renderClock, 60000);
  window.setInterval(refreshWeather, 600000);
}

document.addEventListener("DOMContentLoaded", bootstrapViewer);
