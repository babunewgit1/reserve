/*
==============================================================
    âœ… auth.js for jettly.com
    âœ… connect will globally
==============================================================
*/

function showAuthFormsWrapper() {
   const authFormsWrapper = document.getElementById("authFormsWrapper");
   if (authFormsWrapper) {
      authFormsWrapper.style.display = "block";
   }
}

function hideAuthFormsWrapper() {
   const authFormsWrapper = document.getElementById("authFormsWrapper");
   if (authFormsWrapper) {
      authFormsWrapper.style.display = "none";
   }
}

function updateUIForLoggedInUser(userEmail) {
   const userEmailDisplay = document.getElementById("userEmail");
   const logoutBtn = document.getElementById("logoutBtn");
   // Function to update price visibility
   function updatePriceVisibility() {
      const priceElements = document.querySelectorAll(".item_book .price");
      const signUpBar = document.querySelector(".floating_signup");
      const priceBar = document.querySelectorAll(".view_price_tologin");
      const brokerPax = document.querySelectorAll(".brokerprice_mode");
      if (userEmail && typeof userEmail === "string") {
         priceElements.forEach((price) => {
            price.style.filter = "none";
         });

         if (brokerPax) {
            brokerPax.forEach((brokerprc) => {
               brokerprc.style.filter = "none";
            });
         }

         if (signUpBar) signUpBar.style.display = "none";
         if (priceBar && priceBar.length > 0) {
            priceBar.forEach((bar) => {
               bar.style.display = "none";
            });
         }
      } else {
         priceElements.forEach((price) => {
            price.style.filter = "blur(5px)";
            price.style.userSelect = "none";
            price.style.webkitUserSelect = "none";
            price.style.msUserSelect = "none";
         });

         if (brokerPax) {
            brokerPax.forEach((brokerprc) => {
               brokerprc.style.filter = "blur(5px)";
               brokerprc.style.userSelect = "none";
               brokerprc.style.webkitUserSelect = "none";
               brokerprc.style.msUserSelect = "none";
            });
         }

         if (signUpBar) signUpBar.style.display = "block";
         if (priceBar && priceBar.length > 0) {
            priceBar.forEach((bar) => {
               bar.style.display = "block";
            });
         }
      }
   }

   // Create observer for price elements
   const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
         if (mutation.addedNodes.length) {
            updatePriceVisibility();
         }
      });
   });

   // Start observing
   observer.observe(document.body, {
      childList: true,
      subtree: true,
   });

   if (userEmail && typeof userEmail === "string") {
      const firstLetter = userEmail.charAt(0).toUpperCase();
      userEmailDisplay.textContent = firstLetter;
      userEmailDisplay.style.display = "inline-block";
      document.querySelector(".usermailtext").style.display = "flex";
      document.querySelector(".usermailtext").title = userEmail;
      logoutBtn.style.display = "inline-block";
      hideAuthFormsWrapper();
      document.querySelector(".hd_signup").style.display = "none";
      document.querySelector(".hd_login").style.display = "none";
   } else {
      document.querySelector(".usermailtext").style.display = "none";
      logoutBtn.style.display = "none";
      showAuthFormsWrapper();
      document.querySelector(".hd_signup").style.display = "flex";
      document.querySelector(".hd_login").style.display = "flex";

      if (localStorage.getItem("aircraft_details")) {
         localStorage.removeItem("aircraft_details");
      }
   }
}

// Check login status
function checkLoginStatus() {
   const userEmail = Cookies.get("userEmail");
   const authToken = Cookies.get("authToken");

   if (userEmail && authToken) {
      updateUIForLoggedInUser(userEmail);
      // Check and send flight request IDs if user is logged in
      sendFlightRequestIdsIfLoggedIn();
      // Update Klaviyo tracking for returning user (email only from cookies)
      updateKlaviyoTrackingForReturningUser();
   } else {
      updateUIForLoggedInUser(null);
   }
}

// Update Klaviyo tracking with user data from API response
function updateKlaviyoTrackingFromAPI(apiData) {
   try {
      var responseData = (apiData && apiData.response) || {};
      var userEmail = Cookies.get("userEmail") || responseData.email;
      var firstName = responseData.firstname || "";
      var lastName = responseData.lastname || "";
      var phone = responseData.phone || "";

      // Update Klaviyo identify
      if (
         typeof window.klaviyo !== "undefined" &&
         typeof window.klaviyo.identify === "function"
      ) {
         window.klaviyo.identify({
            $email: userEmail,
            $first_name: firstName,
            $last_name: lastName,
            $phone_number: phone,
         });
      }
   } catch (e) {
      console.error("Failed to update Klaviyo tracking", e);
   }
}

// Update Klaviyo tracking for returning users (email only from cookies)
function updateKlaviyoTrackingForReturningUser() {
   try {
      var userEmail = Cookies.get("userEmail");

      if (userEmail) {
         // Update Klaviyo identify with email only
         if (
            typeof window.klaviyo !== "undefined" &&
            typeof window.klaviyo.identify === "function"
         ) {
            window.klaviyo.identify({
               $email: userEmail,
            });
         }
      }
   } catch (e) {
      console.error("Failed to update Klaviyo tracking for returning user", e);
   }
}

// Track specific page with custom page name (like Sustainability) - LOGGED-IN USERS ONLY
// Usage example: trackSpecificPage("Sustainability");
// This will send: klaviyo.track('Viewed Page', {"page name": "Sustainability"})
function trackSpecificPage(pageName) {
   try {
      const userEmail = Cookies.get("userEmail");

      // Only track if user is logged in
      if (!userEmail) {
         return;
      }

      const fullUrl = window.location.href;
      const currentPage = window.location.pathname;
      const pageTitle = document.title;

      // Identify user first
      if (
         typeof window.klaviyo !== "undefined" &&
         typeof window.klaviyo.identify === "function"
      ) {
         window.klaviyo.identify({ $email: userEmail });
      }

      // Track with custom page name using Klaviyo
      if (
         typeof window.klaviyo !== "undefined" &&
         typeof window.klaviyo.track === "function"
      ) {
         window.klaviyo.track("Viewed Page", {
            "page name": pageName,
            $page_url: fullUrl,
            $page_path: currentPage,
            $page_title: pageTitle,
         });
      }
   } catch (e) {
      console.error("Failed to track specific page", e);
   }
}

// Auto-track current page based on URL path - LOGGED-IN USERS ONLY
function trackCurrentPage() {
   try {
      const userEmail = Cookies.get("userEmail");

      // Only track if user is logged in
      if (!userEmail) {
         return;
      }

      const currentPath = window.location.pathname;
      const pageTitle = document.title;

      // Map URL paths to page names
      let pageName = "";

      if (currentPath === "/" || currentPath === "/home") {
         pageName = "Home";
      } else if (currentPath.includes("/sustainability")) {
         pageName = "Sustainability";
      } else if (currentPath.includes("/about")) {
         pageName = "About Us";
      } else if (currentPath.includes("/contact")) {
         pageName = "Contact";
      } else if (currentPath.includes("/aircraft")) {
         pageName = "Aircraft";
      } else if (currentPath.includes("/checkout")) {
         pageName = "Checkout";
      } else {
         // Use page title as fallback
         pageName = pageTitle || "Unknown Page";
      }

      // Track the page
      trackSpecificPage(pageName);
   } catch (e) {
      console.error("Failed to auto-track current page", e);
   }
}

// Export functions to global scope
window.showAuthFormsWrapper = showAuthFormsWrapper;
window.hideAuthFormsWrapper = hideAuthFormsWrapper;
window.updateUIForLoggedInUser = updateUIForLoggedInUser;
window.checkLoginStatus = checkLoginStatus;
window.trackSpecificPage = trackSpecificPage;
window.trackCurrentPage = trackCurrentPage;

// Initialize auth forms wrapper on page load
document.addEventListener("DOMContentLoaded", () => {
   hideAuthFormsWrapper();
   checkLoginStatus(); // This will check and send flight request IDs

   // Auto-track current page for logged-in users
   setTimeout(() => {
      trackCurrentPage();
   }, 1000); // Small delay to ensure Klaviyo is loaded
});

//toast js
class Toast {
   constructor(element) {
      this.element = element;
   }

   show() {
      this.element.classList.add("show");
      // Auto-hide after 5 seconds
      setTimeout(() => this.hide(), 8000);
   }

   hide() {
      this.element.classList.remove("show");
   }
}

// Initialize toast when DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
   window.toast = new Toast(document.getElementById("notificationToast"));
});

//form.js
document.addEventListener("DOMContentLoaded", () => {
   // Get form elements
   const loginForm = document.getElementById("loginForm");
   const signupForm = document.getElementById("signupForm");
   const forgotPasswordForm = document.getElementById("forgotPasswordForm");
   const logoutBtn = document.getElementById("logoutBtn");

   // Get navigation links
   const showSignupLink = document.getElementById("showSignup");
   const showLoginLink = document.getElementById("showLogin");
   const showForgotPasswordLink = document.getElementById("showForgotPassword");
   const backToLoginLink = document.getElementById("backToLogin");

   // Function to show a specific form and hide others
   const showForm = (formToShow) => {
      [loginForm, signupForm, forgotPasswordForm].forEach((form) => {
         form.style.display = form === formToShow ? "flex" : "none";
      });
   };

   // Event listeners for navigation
   showSignupLink.addEventListener("click", (e) => {
      e.preventDefault();
      showForm(signupForm);
   });

   showLoginLink.addEventListener("click", (e) => {
      e.preventDefault();
      showForm(loginForm);
   });

   showForgotPasswordLink.addEventListener("click", (e) => {
      e.preventDefault();
      showForm(forgotPasswordForm);
   });

   backToLoginLink.addEventListener("click", (e) => {
      e.preventDefault();
      showForm(loginForm);
   });

   signupForm.querySelector("form").addEventListener("submit", (e) => {
      e.preventDefault();
      const password = document.getElementById("signupPassword").value;
      const confirmPassword = document.getElementById("confirmPassword").value;

      if (password !== confirmPassword) {
         alert("Passwords do not match!");
         return;
      }
   });

   // Logout handler
   logoutBtn.addEventListener("click", () => {
      logoutBtn.style.display = "none";
      document.getElementById("userEmail").style.display = "none";
      document.getElementById("userEmail").textContent = "";
      // showForm(loginForm);
   });

   // code for close button in pobup from. when user will click in x cross button popup will hide
   document.querySelectorAll("img.close_img").forEach((closebtn) => {
      closebtn.addEventListener("click", function () {
         closebtn.closest(".auth-form").style.display = "none";
      });
   });

   // code for open login and signup form when user will click in signup and login form main header
   const signUp = document.querySelector(".hd_signup");
   const login = document.querySelector(".hd_login");

   signUp.addEventListener("click", () => {
      signupForm.style.display = "flex";
      loginForm.style.display = "none";
   });

   login.addEventListener("click", () => {
      loginForm.style.display = "flex";
      signupForm.style.display = "none";
   });
});

// Utility function to send flightRequestIds if logged in
async function sendFlightRequestIdsIfLoggedIn() {
   const userEmail = Cookies.get("userEmail");
   const authToken = Cookies.get("authToken");
   const isLoggedIn = userEmail && authToken;
   const storedData = sessionStorage.getItem("flightRequestId");
   const flightRequestIds = JSON.parse(storedData || "[]");

   if (isLoggedIn && flightRequestIds.length > 0) {
      try {
         const response = await fetch(
            "https://operators-dashboard.bubbleapps.io/api/1.1/wf/save_session_requests",
            {
               method: "POST",
               headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${authToken}`,
               },
               body: JSON.stringify({ flightrequestids: flightRequestIds }),
            },
         );

         if (response.ok) {
            sessionStorage.removeItem("flightRequestId");
         } else {
            console.error(
               "Failed to send to backend:",
               response.status,
               response.statusText,
            );
         }
      } catch (err) {
         console.error("Error sending to backend:", err);
      }
   }
}
window.sendFlightRequestIdsIfLoggedIn = sendFlightRequestIdsIfLoggedIn;

//sign up.js
document.addEventListener("DOMContentLoaded", () => {
   const signupForm = document
      .getElementById("signupForm")
      .querySelector("form");
   const toastMessage = document.getElementById("toastMessage");

   signupForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const email = document.getElementById("signupEmail").value;
      const password = document.getElementById("signupPassword").value;
      const confirmPassword = document.getElementById("confirmPassword").value;

      // validate phone Number with the dom plugin
      if (window.iti.isValidNumber()) {
         var internationalNumber = window.iti.getNumber(
            window.intlTelInputUtils.numberFormat.E164,
         );
      } else {
         toastMessage.textContent = "Please enter a valid phone number.";
         toast.show();
         return;
      }

      try {
         const verifyRes = await fetch(
            "https://operators-dashboard.bubbleapps.io/api/1.1/wf/email_phone_verification",
            {
               method: "POST",
               headers: {
                  "Content-Type": "application/json",
               },
               body: JSON.stringify({
                  email: email,
                  phone: internationalNumber,
               }),
            },
         );
         const verifyData = await verifyRes.json();

         // Phone validation logic with abstractapi
         if (!verifyData.response.phone_valid) {
            toastMessage.textContent = "Please enter a valid phone number.";
            toast.show();
            return;
         }

         // Email validation logic with abstractapi
         if (
            verifyData.response.email_status !== "DELIVERABLE" ||
            verifyData.response.disposable_email === true
         ) {
            toastMessage.textContent = "Please enter a valid email";
            toast.show();
            return;
         }
      } catch (err) {
         toastMessage.textContent = "Something wrong!";
         toast.show();
      }

      // Basic validation
      if (password !== confirmPassword) {
         toastMessage.textContent = "Passwords do not match!";
         toast.show();
         return;
      }

      try {
         const response = await fetch(
            "https://operators-dashboard.bubbleapps.io/api/1.1/wf/webflow_signup",
            {
               method: "POST",
               headers: {
                  "Content-Type": "application/json",
               },
               body: JSON.stringify({
                  email: email,
                  password: password,
                  phone: internationalNumber,
               }),
            },
         );

         const data = await response.json();
         if (response.ok) {
            // Use the email from signup form directly
            const userEmail = email;
            // Store user data in cookies
            Cookies.set("userEmail", userEmail, { expires: 7, secure: true });
            if (data.response && data.response.token) {
               Cookies.set("authToken", data.response.token, {
                  expires: 7,
                  secure: true,
               });
            }

            // Set a key in local storage to verify the user is new
            localStorage.setItem("new_user", "true");

            // TATARI TRACKING: Identify user and track signup event
            if (typeof tatari !== "undefined" && data.response.user_id) {
               tatari.identify(data.response.user_id);
               tatari.track("Sign Up", {
                  user_id: data.response.user_id,
               });
            }

            // Update Klaviyo tracking with API response data
            updateKlaviyoTrackingFromAPI(data);

            // Update UI
            updateUIForLoggedInUser(userEmail);
            document.getElementById("signupForm").style.display = "none";

            // Dispatch login success event
            window.dispatchEvent(new Event("loginSuccess"));

            toastMessage.textContent = "Signup successful!";
            toast.show();

            // Send flight request IDs if any exist
            sendFlightRequestIdsIfLoggedIn();

            // Clear the form
            signupForm.reset();
            const currentPath = window.location.pathname;
            if (
               (currentPath === "/aircraft" || currentPath === "/aircraft/") &&
               localStorage.getItem("aircraft_details")
            ) {
               window.location.href = "/checkout";
            }
         } else {
            toastMessage.textContent =
               "Signup failed: " + (data.message || "Unknown error");
            toast.show();
         }
      } catch (error) {
         toastMessage.textContent =
            "An error occurred during signup. Please try again.";
         toast.show();
      }
   });
});

//login.js
document.addEventListener("DOMContentLoaded", () => {
   const loginForm = document.getElementById("loginForm").querySelector("form");
   const toast = window.toast;
   const toastMessage = document.getElementById("toastMessage");
   const logoutBtn = document.getElementById("logoutBtn");

   loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const email = document.getElementById("loginEmail").value;
      const password = document.getElementById("loginPassword").value;

      try {
         const response = await fetch(
            "https://operators-dashboard.bubbleapps.io/api/1.1/wf/webflow_login",
            {
               method: "POST",
               headers: {
                  "Content-Type": "application/json",
               },
               body: JSON.stringify({
                  email: email,
                  password: password,
               }),
            },
         );

         const data = await response.json();
         if (response.ok) {
            if (data && data.response) {
               const userEmail = email;

               if (userEmail) {
                  // Store user data in cookies
                  Cookies.set("userEmail", userEmail, {
                     expires: 7,
                     secure: true,
                  });
                  if (data.response.token) {
                     Cookies.set("authToken", data.response.token, {
                        expires: 7,
                        secure: true,
                     });
                  }

                  // TATARI TRACKING: Identify user and track login event
                  if (typeof tatari !== "undefined" && data.response.user_id) {
                     tatari.identify(data.response.user_id);
                     tatari.track("Login", {
                        user_id: data.response.user_id,
                     });
                  }

                  // Update Klaviyo tracking with API response data
                  updateKlaviyoTrackingFromAPI(data);

                  // Update UI
                  updateUIForLoggedInUser(userEmail);
                  document.getElementById("loginForm").style.display = "none";

                  // Dispatch login success event
                  window.dispatchEvent(new Event("loginSuccess"));

                  toastMessage.textContent = "Login successful!";
                  toast.show();

                  // Send flight request IDs if any exist
                  sendFlightRequestIdsIfLoggedIn();

                  // Clear the form
                  loginForm.reset();
                  const currentPath = window.location.pathname;
                  if (
                     (currentPath === "/aircraft" ||
                        currentPath === "/aircraft/") &&
                     localStorage.getItem("aircraft_details")
                  ) {
                     window.location.href = "/checkout";
                  }
               }
            }
         } else {
            toastMessage.textContent =
               "Login failed: " + (data.message || "Invalid credentials");
            toast.show();
         }
      } catch (error) {
         toastMessage.textContent =
            "An error occurred during login. Please try again.";
         toast.show();
      }
   });

   // Handle logout
   logoutBtn.addEventListener("click", () => {
      // Clear cookies
      Cookies.remove("userEmail");
      Cookies.remove("authToken");

      // Clear session user details
      sessionStorage.removeItem("userDetails");

      // Update UI for logged out user
      updateUIForLoggedInUser(null);
      toastMessage.textContent = "Logged out successfully!";
      toast.show();
      //remove key from local storage to verify the user is new
      localStorage.removeItem("new_user");
   });
});

//forget_password.js
document.addEventListener("DOMContentLoaded", () => {
   const forgotPasswordForm = document
      .getElementById("forgotPasswordForm")
      .querySelector("form");
   const toast = window.toast;
   const toastMessage = document.getElementById("toastMessage");

   forgotPasswordForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const email = document.getElementById("resetEmail").value;

      try {
         const response = await fetch(
            "https://operators-dashboard.bubbleapps.io/api/1.1/wf/webflow_forgotpassword",
            {
               method: "POST",
               headers: {
                  "Content-Type": "application/json",
               },
               body: JSON.stringify({
                  email: email,
               }),
            },
         );

         const data = await response.json();
         if (response.ok) {
            toastMessage.textContent =
               "Password reset instructions sent to your email!";
            toast.show();
            // Clear the form
            forgotPasswordForm.reset();
         } else {
            toastMessage.textContent =
               "Password reset failed: " + (data.message || "Unknown error");
            toast.show();
         }
      } catch (error) {
         toastMessage.textContent =
            "An error occurred during password reset. Please try again.";
         toast.show();
      }
   });
});
