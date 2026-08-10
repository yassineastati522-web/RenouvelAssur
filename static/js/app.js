(() => {
  const navToggle = document.querySelector("[data-nav-toggle]");
  const navClose = document.querySelector("[data-nav-close]");

  navToggle?.addEventListener("click", () => {
    document.body.classList.toggle("nav-open");
  });
  navClose?.addEventListener("click", () => {
    document.body.classList.remove("nav-open");
  });

  const expiry = document.body.dataset.sessionExpiry;
  const loginUrl = document.body.dataset.loginUrl;
  if (!expiry || !loginUrl) return;

  const remaining = Date.parse(expiry) - Date.now();
  const leaveApplication = () => window.location.replace(loginUrl);
  if (remaining <= 0) leaveApplication();
  else window.setTimeout(leaveApplication, remaining);
})();
