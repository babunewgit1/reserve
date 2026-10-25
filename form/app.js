const API_BASE = "https://operators-dashboard.bubbleapps.io/api/1.1/wf";
const GENERIC_ERROR = "Something went wrong. Please try again.";
const CALENDLY_URL =
   "https://calendly.com/jettly-membership-sales/general-sales?hide_event_type_details=1&hide_gdpr_banner=1&primary_color=ff5d47";

// Reset all fields back to their initial state
function resetForm(form) {
   form.reset();
   if (window.iti) window.iti.setNumber("");
}

// Show the Calendly inline widget after a successful submission
function openCalendly(form) {
   const widget = document.createElement("div");
   widget.className = "calendly-inline-widget";
   widget.setAttribute("data-url", CALENDLY_URL);
   widget.style.cssText =
      "min-width:320px;height:600px;border-radius:10px;overflow:hidden;";
   form.style.display = "none";
   form.after(widget);

   if (window.Calendly) {
      window.Calendly.initInlineWidget({
         url: CALENDLY_URL,
         parentElement: widget,
      });
      return;
   }

   if (!document.getElementById("calendly-widget-script")) {
      const script = document.createElement("script");
      script.id = "calendly-widget-script";
      script.src = "https://assets.calendly.com/assets/external/widget.js";
      script.async = true;
      document.body.appendChild(script);
   }
}

// toast message
function ensureToast() {
   if (window.toast && document.getElementById("toastMessage")) return;

   let toastEl = document.getElementById("notificationToast");
   if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.id = "notificationToast";
      toastEl.style.cssText =
         "position:fixed;top:2rem;right:0;z-index:10000000;min-width:350px;" +
         "background:#ff5d47;color:#fff;padding:1rem;border-radius:4px 0 0 4px;" +
         "box-shadow:0 4px 12px rgba(0,0,0,.15);display:none;";
      const msg = document.createElement("div");
      msg.id = "toastMessage";
      toastEl.appendChild(msg);
      document.body.appendChild(toastEl);
   }

   if (!window.toast) {
      window.toast = {
         show() {
            toastEl.classList.add("show");
            toastEl.style.display = "block";
            clearTimeout(this._t);
            this._t = setTimeout(() => this.hide(), 5000);
         },
         hide() {
            toastEl.classList.remove("show");
            toastEl.style.display = "none";
         },
      };
   }
}

function showMessage(message) {
   ensureToast();
   document.getElementById("toastMessage").textContent = message;
   window.toast.show();
}

// Turn off the browser's native validation bubbles so our toast is shown instead,
// and clear the form on every page load / reload (browsers restore old values).
function getJvForm() {
   const btn = document.querySelector(".jv_form_submit");
   return btn && btn.closest("form");
}

document.addEventListener("DOMContentLoaded", function () {
   const form = getJvForm();
   if (form) {
      form.noValidate = true;
      form.setAttribute("autocomplete", "off");
      resetForm(form);
   }
});

// Reload / back-forward cache: browsers may restore old values after DOMContentLoaded
window.addEventListener("pageshow", function () {
   const form = getJvForm();
   if (form) resetForm(form);
});

// Capture phase on window runs before Webflow's own submit handlers,
// so stopImmediatePropagation() prevents them from running (and reloading the page).
window.addEventListener(
   "submit",
   async function (e) {
      const form = e.target;
      if (!form.querySelector || !form.querySelector(".jv_form_submit")) return;

      e.preventDefault();
      e.stopImmediatePropagation();

      const submitBtn = form.querySelector(".jv_form_submit button");
      const originalText = submitBtn ? submitBtn.textContent : "";

      const fname = document.getElementById("fvfirstname").value.trim();
      const lname = document.getElementById("fvlastname").value.trim();
      const email = document.getElementById("fvemail").value.trim();
      const hours = parseFloat(document.getElementById("fvhours").value);
      const primaryCategory = form.querySelector(".fvinp_block select").value;

      // Required field validation (shown as toast)
      if (!fname) {
         showMessage("Please enter your first name.");
         return;
      }
      if (!lname) {
         showMessage("Please enter your last name.");
         return;
      }
      if (!email) {
         showMessage("Please enter your email.");
         return;
      }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
         showMessage("Please enter a valid email.");
         return;
      }
      const phoneInput = form.querySelector('input[name="phone"]');
      if (!phoneInput || !phoneInput.value.trim()) {
         showMessage("Please enter your phone number.");
         return;
      }
      if (!document.getElementById("fvhours").value.trim()) {
         showMessage("Please enter your estimated annual flight hours.");
         return;
      }
      if (isNaN(hours)) {
         showMessage("Please enter a valid number for flight hours.");
         return;
      }
      if (!primaryCategory) {
         showMessage("Please select a primary aircraft category.");
         return;
      }

      if (!form.querySelector('.fvinp_check input[type="checkbox"]:checked')) {
         showMessage("Please select at least one aviation solution.");
         return;
      }

      if (!window.iti || !window.iti.isValidNumber()) {
         showMessage("Please enter a valid phone number.");
         return;
      }
      const internationalNumber = window.iti.getNumber(
         window.intlTelInputUtils.numberFormat.E164,
      );

      if (submitBtn) {
         submitBtn.disabled = true;
         submitBtn.textContent = "Please wait...";
      }

      try {
         const verifyRes = await fetch(`${API_BASE}/email_phone_verification`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
               email: email,
               phone: internationalNumber,
            }),
         });
         const verifyData = await verifyRes.json().catch(() => ({}));

         if (!verifyRes.ok || !verifyData.response) {
            showMessage(GENERIC_ERROR);
            return;
         }

         if (!verifyData.response.phone_valid) {
            showMessage("Please enter a valid phone number.");
            return;
         }

         if (
            verifyData.response.email_status !== "DELIVERABLE" ||
            verifyData.response.disposable_email === true
         ) {
            showMessage("Please enter a valid email");
            return;
         }

         const isChecked = (id) =>
            document.getElementById(id).checked ? "yes" : "no";

         const payload = {
            fname: fname,
            lname: lname,
            email: email,
            phone: internationalNumber,
            estimated_hours: hours,
            primary_category: primaryCategory,
            charter: isChecked("chk1"),
            jetcard: isChecked("chk2"),
            fractional: isChecked("chk3"),
            commercial: isChecked("chk5"),
            other: isChecked("chk6"),
         };

         const response = await fetch(
            `${API_BASE}/flyt_jettly_form_submission`,
            {
               method: "POST",
               headers: { "Content-Type": "application/json" },
               body: JSON.stringify(payload),
            },
         );
         const data = await response.json().catch(() => ({}));

         if (!response.ok) {
            showMessage(GENERIC_ERROR);
            return;
         }

         // Success: clear the form, then show Calendly
         resetForm(form);
         showMessage("Form submitted successfully!");
         openCalendly(form);
      } catch (err) {
         showMessage(GENERIC_ERROR);
      } finally {
         if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
         }
      }
   },
   true,
);
