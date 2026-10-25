/*
==============================================================
    ✅ Search.js for jettly.com
    ✅ connect will in aircraft page
==============================================================
*/

sessionStorage.removeItem("checkedItems");
// Debounce utility for search input
function debounce(fn, delay) {
   let timeout;
   return (...args) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => fn(...args), delay);
   };
}

let checkedItems = {};
const storedCheckedItems = sessionStorage.getItem("checkedItems");
if (storedCheckedItems) {
   checkedItems = JSON.parse(storedCheckedItems);
}

// Global variables
let apiData = {};
let aircraftSets = [];
let filteredByRangeSlider = [];
let longestFlight;
let flightRequestId;
let tripClassification = "";
let minYear, maxYear, minYearExt, minYearInt, minYearIns, maxYearIns;

let currentMinPrice;
let currentMaxPrice;

// Function to check if user is logged in
function isUserLoggedIn() {
   const userEmail = Cookies.get("userEmail");
   const authToken = Cookies.get("authToken");
   return !!(userEmail && authToken);
}

// Function to fetch hot deal pricing from API
async function fetchHotDealPricing(category, itemElement) {
   try {
      const authToken = Cookies.get("authToken");
      if (!authToken || !flightRequestId) {
         return;
      }

      // Find the tax text element and set loading state
      const taxTextElement = itemElement.querySelector("p");
      if (taxTextElement) {
         taxTextElement.textContent = "Fetching best pricing...";
      }

      const response = await fetch(
         "https://operators-dashboard.bubbleapps.io/api/1.1/wf/instant_book_pricing",
         {
            method: "POST",
            headers: {
               "Content-Type": "application/json",
               Authorization: `Bearer ${authToken}`,
            },
            body: JSON.stringify({
               flightrequestid: flightRequestId,
               category: category,
            }),
         },
      );

      if (!response.ok) {
         throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      if (data.status === "success" && data.response) {
         // Update the price elements in the item
         const mainPriceEl = itemElement.querySelector(".main_price");
         const hourlyRateEl = itemElement.querySelector(".hourly_rate");

         if (mainPriceEl && data.response.price) {
            mainPriceEl.textContent = `$${Math.round(
               data.response.price,
            ).toLocaleString()}`;
         }

         if (hourlyRateEl && data.response.hourly_rate) {
            hourlyRateEl.textContent = `$${Math.round(
               data.response.hourly_rate,
            ).toLocaleString()}/hr`;
         }

         // Update the data-calculated-price attribute on the details button
         const itemWrapper = itemElement.closest(".item_wrapper");
         if (itemWrapper && data.response.price) {
            const detailsButton = itemWrapper.querySelector(".details-button");
            if (detailsButton) {
               detailsButton.setAttribute(
                  "data-calculated-price",
                  Math.round(data.response.price),
               );
            }
         }

         // Update the global aircraftCalculatedValues with API price for hot deals
         const itemId = itemElement.getAttribute("data-item-id");
         if (itemId && data.response.price) {
            window.aircraftCalculatedValues[itemId] = Math.round(
               data.response.price,
            );
         }

         // Update fuel stop visibility based on techstops
         if (itemId) {
            const fuelStopElements = document.querySelectorAll(
               `.hot-deal-fuel-stop[data-item-id="${itemId}"]`,
            );
            const techstops = data.response.techstops || 0;

            fuelStopElements.forEach((el) => {
               if (techstops > 0) {
                  el.style.display = "block";
               } else {
                  el.style.display = "none";
               }
            });
         }

         // Restore original tax text after successful API call
         const taxTextElement = itemElement.querySelector("p");
         if (taxTextElement) {
            taxTextElement.textContent = "Final Price + Tax at Checkout";
         }
      }
   } catch (error) {
      console.error("Error fetching hot deal pricing:", error);
      // Restore original tax text on error
      const taxTextElement = itemElement.querySelector("p");
      if (taxTextElement) {
         taxTextElement.textContent = "Final Price + Tax at Checkout";
      }
   }
}

// Function to update all hot deal prices on the page
async function updateHotDealPricing() {
   const hotDealItems = document.querySelectorAll(
      ".hotwrapper .price[data-hot-deal-category]",
   );

   // Create an array of promises for all API calls
   const fetchPromises = Array.from(hotDealItems).map((priceElement) => {
      const category = priceElement.getAttribute("data-hot-deal-category");
      if (category) {
         return fetchHotDealPricing(category, priceElement);
      }
      return Promise.resolve();
   });

   // Wait for all API calls to complete simultaneously
   await Promise.all(fetchPromises);
}

// Function to re-render current page when login status changes
// This ensures hot deals are properly added/removed from DOM (not just hidden)
function handleLoginStatusChange() {
   // Re-render the current page with updated login status
   if (typeof filterAndRender === "function") {
      filterAndRender(currentPage);
   }
}

// Filter state arrays
let selectedClasses = [];
let selectedDescriptions = [];
let selectedOperators = [];
let selectedArgusFilters = [];
let selectedIsBaoFilters = [];
let selectedWyvernFilters = [];
let selectedanimalFilters = [];
let selectedOthersFilters = [];
let fuelFilters = [];

// Pagination variables
const itemsPerPage = 20;
let currentPage = 1;
let globalIndex = 0; // To ensure unique indexing for hot deals and regular items.

// DOM elements
const mainWrapper = document.querySelector(".search_right");
const pagination = document.querySelector(".pagination");
const categoryCheckboxWrapper = document.querySelector(".sr_catagory_checkbox");
const descriptionCheckboxWrapper = document.querySelector(".dis_checkbox");
const sellerCheckboxWrapper = document.querySelector(".seller_checkbox");
const argusCheckboxWrapper = document.querySelector(".argus_checkbox");
const isBaoCheckboxWrapper = document.querySelector(".is_bao");
const wyvernCheckboxWrapper = document.querySelector(".wyvern");
const animalCheckboxWrapper = document.querySelector(".amenities");
const othersCheckboxWrapper = document.querySelector(".otherscheck");
const fuelCheckboxWrapper = document.querySelector(".fuel_stop");
const rangeSlider = document.getElementById("range");
const rangeValueDisplay = document.getElementById("range_value");
const departureReadyCheckbox = document.getElementById("departureReady");
const highTimeCrewCheckbox = document.getElementById("highTimeCrew");
const extSlider = document.getElementById("extslider");
const extValueDisplay = document.getElementById("exttextvalue");
const intSlider = document.getElementById("intslider");
const intValueDisplay = document.getElementById("inttextvalue");
const insSlider = document.getElementById("insslider");
const insValueDisplay = document.getElementById("instextvalue");
const searchInputBox = document.getElementById("searchBox");
const finalResultParagraph = document.getElementById("finalresult");
const loader = document.querySelector(".loading_animation");
const filterTextElement = document.querySelector(".filter_number");

const departureReadyCountLabel = departureReadyCheckbox
   .closest("label")
   .querySelector("span");
const highTimeCrewCountLabel = highTimeCrewCheckbox
   .closest("label")
   .querySelector("span");

// Function to update the count of selected filters
function updateSelectedFilterCount() {
   let totalSelected = 0;
   totalSelected += selectedClasses.length;
   totalSelected += selectedDescriptions.length;
   totalSelected += selectedOperators.length;
   totalSelected += selectedArgusFilters.length;
   totalSelected += selectedIsBaoFilters.length;
   totalSelected += selectedWyvernFilters.length;
   totalSelected += selectedanimalFilters.length;
   totalSelected += selectedOthersFilters.length;
   totalSelected += fuelFilters.length;
   if (departureReadyCheckbox.checked) totalSelected += 1;
   if (highTimeCrewCheckbox.checked) totalSelected += 1;
   filterTextElement.textContent = `${totalSelected}`;
}

const showLoader = () => {
   loader.style.display = "flex";
};
const hideLoader = () => {
   loader.style.display = "none";
};

// Show loader initially
showLoader();

// Function to recalculate fuel counts based on flight legs
function recalculateFuelCounts(items) {
   const fuelCount = {
      Direct: 0,
      "1 Stop": 0,
      "2 Stop": 0,
      "": 0,
   };

   items.forEach((item) => {
      if (item.range_number > longestFlight) {
         fuelCount["Direct"]++;
      } else if (item.range_number * 2 > longestFlight) {
         fuelCount["1 Stop"]++;
      } else if (item.range_number * 2 < longestFlight) {
         fuelCount["2 Stop"]++;
      } else {
         fuelCount[""]++;
      }
   });

   return fuelCount;
}

// Function to update generic checkbox counts
function updateGenericCount(items, wrapper, key) {
   const counts = items.reduce((acc, item) => {
      const keyValue = item[key];
      acc[keyValue] = (acc[keyValue] || 0) + 1;
      return acc;
   }, {});
   wrapper.querySelectorAll(".checkbox_item").forEach((item) => {
      const checkbox = item.querySelector("input[type='checkbox']");
      const label = item.querySelector("label span");
      const val = checkbox.value;
      label.textContent = `(${counts[val] || 0})`;
   });
}

// Function to update boolean filter checkbox counts
function updateBooleanFilterCount(items, wrapper, filters) {
   const counts = {};
   filters.forEach((f) => {
      counts[f.name] = items.filter((item) => item[f.key] === true).length;
   });

   wrapper.querySelectorAll(".checkbox_item").forEach((item) => {
      const checkbox = item.querySelector("input[type='checkbox']");
      const label = item.querySelector("label span");
      const val = checkbox.value;
      label.textContent = `(${counts[val] || 0})`;
   });
}

// Function to update all checkbox counts based on filtered sets
function updateCheckboxCounts(filteredSets) {
   requestAnimationFrame(() => {
      const fuelCount = recalculateFuelCounts(filteredSets);

      fuelCheckboxWrapper.querySelectorAll(".checkbox_item").forEach((item) => {
         const checkbox = item.querySelector("input[type='checkbox']");
         const label = item.querySelector("label span");
         const filter = checkbox.value;
         label.textContent = `(${fuelCount[filter] || 0})`;
      });

      const departureReadyCount = filteredSets.filter(
         (item) => item.departure_ready__boolean === true,
      ).length;
      departureReadyCountLabel.textContent = `(${departureReadyCount})`;

      const highTimeCrewCount = filteredSets.filter(
         (item) => item.high_time_crew__boolean === true,
      ).length;
      highTimeCrewCountLabel.textContent = `(${highTimeCrewCount})`;

      updateGenericCount(filteredSets, categoryCheckboxWrapper, "class_text");
      updateGenericCount(
         filteredSets,
         descriptionCheckboxWrapper,
         "description_text",
      );
      updateGenericCount(
         filteredSets,
         sellerCheckboxWrapper,
         "operator_txt_text",
      );

      updateBooleanFilterCount(filteredSets, argusCheckboxWrapper, [
         { name: "Not Rated", key: "argus_not_rated__boolean" },
         { name: "Gold", key: "argus_gold__boolean" },
         { name: "Gold +", key: "argus_gold____boolean" },
         { name: "Platinum", key: "argus_platinum__boolean" },
      ]);

      updateBooleanFilterCount(filteredSets, isBaoCheckboxWrapper, [
         { name: "Not Rated", key: "is_bao_not_rated__boolean" },
         { name: "Registered", key: "is_bao_registered__boolean" },
      ]);

      updateBooleanFilterCount(filteredSets, wyvernCheckboxWrapper, [
         { name: "Not Rated", key: "wyvern_not_rated__boolean" },
         { name: "Wyvern Registered", key: "wyvern_registered__boolean" },
         { name: "Wyvern Wingman", key: "wyvern_wingman__boolean" },
      ]);

      updateBooleanFilterCount(filteredSets, animalCheckboxWrapper, [
         { name: "Enclosed Lavatory", key: "enclosed_lavatory__boolean" },
         { name: "Pets Allowed", key: "pet_friendly__boolean" },
         { name: "Smoking Allowed", key: "smoking_allowed__boolean" },
         { name: "Wi-Fi (Ground based)", key: "wi_fi_ground_based__boolean" },
         {
            name: "Wi-Fi (Satellite based)",
            key: "wi_fi_satellite_based__boolean",
         },
      ]);

      updateBooleanFilterCount(filteredSets, othersCheckboxWrapper, [
         { name: "Exclude owner approval", key: "oa_required__boolean" },
         { name: "Cargo", key: "cargo_capable__boolean" },
         { name: "Ambulance", key: "ambulance_capable__boolean" },
         { name: "Exclude transient", key: "transient_aircraft__boolean" },
         { name: "Exclude at homebase", key: "at_home_base__boolean" },
      ]);
   });
}

// Functions to apply different filters
function applyArgusFilters(sets, filters) {
   return sets.filter((item) => {
      return filters.some((filter) => {
         if (filter === "Not Rated") return item.argus_not_rated__boolean;
         if (filter === "Gold") return item.argus_gold__boolean;
         if (filter === "Gold +") return item.argus_gold____boolean;
         if (filter === "Platinum") return item.argus_platinum__boolean;
         return false;
      });
   });
}

function applyIsBaoFilters(sets, filters) {
   return sets.filter((item) => {
      return filters.some((filter) => {
         if (filter === "Not Rated") return item.is_bao_not_rated__boolean;
         if (filter === "Registered") return item.is_bao_registered__boolean;
         return false;
      });
   });
}

function applyWyvernFilters(sets, filters) {
   return sets.filter((item) => {
      return filters.some((filter) => {
         if (filter === "Not Rated") return item.wyvern_not_rated__boolean;
         if (filter === "Wyvern Registered")
            return item.wyvern_registered__boolean;
         if (filter === "Wyvern Wingman") return item.wyvern_wingman__boolean;
         return false;
      });
   });
}

function applyAnimalFilters(sets, filters) {
   return sets.filter((item) => {
      return filters.some((filter) => {
         if (filter === "Enclosed Lavatory")
            return item.enclosed_lavatory__boolean;
         if (filter === "Pets Allowed") return item.pet_friendly__boolean;
         if (filter === "Smoking Allowed") return item.smoking_allowed__boolean;
         if (filter === "Wi-Fi (Ground based)")
            return item.wi_fi_ground_based__boolean;
         if (filter === "Wi-Fi (Satellite based)")
            return item.wi_fi_satellite_based__boolean;
         return false;
      });
   });
}

function applyOthersFilters(sets, filters) {
   return sets.filter((item) => {
      return filters.some((filter) => {
         if (filter === "Exclude owner approval")
            return item.oa_required__boolean;
         if (filter === "Cargo") return item.cargo_capable__boolean;
         if (filter === "Ambulance") return item.ambulance_capable__boolean;
         if (filter === "Exclude transient")
            return item.transient_aircraft__boolean;
         if (filter === "Exclude at homebase")
            return item.at_home_base__boolean;
         return false;
      });
   });
}

function applyFuelFilters(sets, filters) {
   return sets.filter((item) => {
      let stopCategory;
      if (item.range_number > longestFlight) {
         stopCategory = "Direct";
      } else if (item.range_number * 2 > longestFlight) {
         stopCategory = "1 Stop";
      } else if (item.range_number * 2 < longestFlight) {
         stopCategory = "2 Stop";
      } else {
         stopCategory = "";
      }
      return filters.includes(stopCategory);
   });
}

// Function to update the display div with checked items
function updateCheckedItemsDisplay() {
   const displayDiv = document.getElementById("checkedItemsDiv");
   if (!displayDiv) return;

   const checkedIds = Object.keys(checkedItems);
   if (checkedIds.length === 0) {
      displayDiv.innerHTML = "<p>No items selected.</p>";
      return;
   }

   // Fetch details of checked items
   const checkedItemsDetails = aircraftSets.filter((item) => {
      const itemId = item._id || `item-${aircraftSets.indexOf(item)}`;
      return checkedIds.includes(itemId);
   });

   // Generate HTML to display (customize as needed)
   const html = checkedItemsDetails
      .map(
         (item) => `
    <div class="selected-item">
      <img src="${item.exterior_image1_image}" alt="${item.description_text}" />
      <p>${item.description_text}</p>
      <p>Pax: ${item.pax_number}</p>
      <p>Year: ${item.year_of_manufacture_number}</p>
      <p>Operator: ${item.operator_txt_text}</p>
      <p>Price: $${item.price_per_hour_fixedrate_number.toLocaleString()}</p>
    </div>
  `,
      )
      .join("");

   displayDiv.innerHTML = html;
}

document.querySelector(".crosspop").addEventListener("click", function () {
   document.querySelector(".popupwrapper").style.display = "none";
});

// Function to handle the .request_br_btn click
function handleRequestBrBtnClick() {
   document.querySelector(".selecteditemscontainer").innerHTML = "";
   const selectedItems = aircraftSets.filter((item) => {
      const itemId = item._id || `item-${aircraftSets.indexOf(item)}`;
      return checkedItems[itemId];
   });

   const checkedIds = Object.keys(checkedItems);

   if (checkedIds.length < 1) {
      alert("No items selected.");
      return;
   }
   document.querySelector(".popupwrapper").style.display = "flex";

   // Reference to the container where you want to display the selected items
   const selectedItemsContainer = document.getElementById(
      "selectedItemsContainer",
   );
   if (!selectedItemsContainer) {
      console.error("selectedItemsContainer div not found.");
      return;
   }

   const tripName = document.querySelector(".tripname");
   tripName.innerHTML = "";

   const leg = apiData.response.flight_legs;

   const filterleg = leg
      .map((leg) => {
         const dateStart = leg.date_date;

         // Parse date string to prevent timezone shifting
         let year, month, day;

         if (typeof dateStart === "string") {
            const dateStr = dateStart.split("T")[0]; // Get date part before 'T'
            [year, month, day] = dateStr.split("-");
         } else {
            // If it's a Date object, extract date components directly (no UTC conversion)
            const dateObj = new Date(dateStart);
            year = dateObj.getFullYear();
            month = dateObj.getMonth() + 1; // getMonth() returns 0-11
            day = dateObj.getDate();
         }

         // Create date WITHOUT timezone shifting
         const selectedDate = new Date(year, month - 1, day);

         const formattedDateStart = selectedDate.toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
         });

         // For time formatting
         const fullDateObj = new Date(dateStart);
         const formattedTimeStart = fullDateObj.toLocaleTimeString("en-US", {
            hour: "numeric",
            minute: "2-digit",
            hour12: true,
         });

         return `
      <div class="legoption">
        <p>${formattedDateStart} ${formattedTimeStart}, |</p>
        <div class="airportformatname">
          <p>
            ${
               leg.mobile_app_from_airport_iata_code_text
                  ? leg.mobile_app_from_airport_iata_code_text
                  : leg.mobile_app_from_airport_icao_code_text
                    ? leg.mobile_app_from_airport_icao_code_text
                    : leg.mobile_app_from_airport_faa_code_text || "N/A"
            }
            -
            ${
               leg.mobile_app_to_airport_iata_code_text
                  ? leg.mobile_app_to_airport_iata_code_text
                  : leg.mobile_app_to_airport_icao_code_text
                    ? leg.mobile_app_to_airport_icao_code_text
                    : leg.mobile_app_to_airport_faa_code_text || "N/A"
            }, |
          </p>
        </div>
        <p>${leg.pax1_number} PAX</p>
      </div>
    `;
      })
      .join("");

   tripName.innerHTML = `
    <div class="tripname_wrap">
      <div class="tripleft">
        <h3>Trip name:</h3>
        <p>${apiData.response.trip_name}</p>
      </div>
      <div class="tripright">
        <h3>Itinerary:</h3>
        <div class="triprightcnt">
          ${filterleg}
        </div>
      </div>
    </div>
  `;

   // Clear previous content
   selectedItemsContainer.innerHTML = "";

   // Generate and append HTML for each selected item
   selectedItems.forEach((item, index) => {
      const uniqueId = item._id || `item-${aircraftSets.indexOf(item)}`;
      const decimalTime = `${item.year_of_manufacture_number}`;

      const html = `
      <div class="broker_mode_cnt">
        <div class="broker_item" data-index="${index}">
          <div class="broker_item_img_wrapper">
            <div class="broker_item_img">
              <img src="${item.exterior_image1_image}" alt="${
                 item.description_text
              }" />
            </div>
            <div class="broker_item_para">
              <p>${item.description_text}</p>
            </div>
          </div>
          <div class="broker_pax">
            <p>${item.pax_number}</p>
          </div>
          <div class="broker_pax">
            <p>${item.year_of_manufacture_number}</p>
          </div>
          <div class="broker_pax">
            <p>${decimalTime}</p>
          </div>
          <div class="broker_pax" style="display: none;">
            <p>2.52 KMKE</p>
          </div>
          <div class="broker_pax">
            <p>${item.operator_txt_text}</p>
          </div>
          <div class="broker_pax brokerprice_mode">
            <p>$${item.price_per_hour_fixedrate_number.toLocaleString()}</p>
          </div>
        </div>
        <div class="broker_checkbox">
        <label class="check-box">
          <input type="checkbox" data-id="${uniqueId}" />
          <span class="checkmark"></span>
        </label>
        </div>
      </div>
    `;
      selectedItemsContainer.insertAdjacentHTML("beforeend", html);
   });
   attachPopupCheckboxListeners();
   selectedItemsContainer.scrollIntoView({ behavior: "smooth" });
}

document
   .querySelector(".request_br_btn")
   .addEventListener("click", handleRequestBrBtnClick);

// Function to attach event listeners to popup checkboxes
function attachPopupCheckboxListeners() {
   document
      .querySelectorAll(
         '#selectedItemsContainer .broker_checkbox input[type="checkbox"]',
      )
      .forEach((checkbox) => {
         const uniqueId = checkbox.getAttribute("data-id");
         if (uniqueId) {
            // Ensure checkbox reflects the state
            checkbox.checked = checkedItems[uniqueId] || false;

            // Add event listener to update checkedItems
            checkbox.addEventListener("change", (e) => {
               if (e.target.checked) {
                  // If checked in popup
                  checkedItems[uniqueId] = true;
               } else {
                  // If unchecked in popup
                  delete checkedItems[uniqueId];
                  // Remove the item from the popup
                  // e.target.closest(".broker_mode_cnt").remove();
               }
               // Persist the state to sessionStorage
               sessionStorage.setItem(
                  "checkedItems",
                  JSON.stringify(checkedItems),
               );
               // Update the main list checkboxes
               const mainCheckbox = document.querySelector(
                  `.broker_checkbox input[data-id="${uniqueId}"]`,
               );
               if (mainCheckbox) {
                  mainCheckbox.checked = e.target.checked;
               }
               // Update the display div (if applicable)
               updateCheckedItemsDisplay();
            });
         }
      });
}

// Function to render a page of items
function renderPage(page, filteredSets) {
   const distance = apiData.response.total_distance;

   const TimeDown =
      apiData.response.flight_legs[0].total_distance__statute_m__number;

   const hotDeals = apiData.response.hot_deal_aircraft;
   mainWrapper.innerHTML = "";

   const fragment = document.createDocumentFragment();

   // Only render hot deals if user is logged in (security measure)
   const isLoggedIn = isUserLoggedIn();
   if (
      hotDeals &&
      page === 1 &&
      isLoggedIn &&
      tripClassification === "airplane"
   ) {
      hotDeals.forEach((item) => {
         createItemBlock(item, globalIndex, true, fragment, distance, TimeDown);
         globalIndex++;
      });
   }

   const start = (page - 1) * itemsPerPage;
   const end = start + itemsPerPage;
   const itemsToRender = filteredSets.slice(start, end);

   itemsToRender.forEach((item) => {
      createItemBlock(item, globalIndex, false, fragment, distance, TimeDown);
      globalIndex++;
   });

   mainWrapper.appendChild(fragment);

   //code for print info with "request booking" button for reqular html
   const requestBookingBtn = document.querySelectorAll(".bookinglink");
   const authFormsWrapper = document.getElementById("authFormsWrapper");
   const loginForm = document.getElementById("loginForm");
   const paraPopUp = document.querySelectorAll(".view_price_tologin");

   requestBookingBtn.forEach((bookingBtn) => {
      bookingBtn.addEventListener("click", (e) => {
         e.preventDefault();

         const storedData = sessionStorage.getItem("storeData");
         const parsedData = storedData ? JSON.parse(storedData) : {};

         const aircraftDetails = {
            type: bookingBtn.dataset.type,
            flightRequestId: bookingBtn.dataset.flightrequestid,
            aircraftId: bookingBtn.dataset.aircraftid,
            price:
               window.aircraftCalculatedValues[bookingBtn.dataset.aircraftid] ||
               0,
            fare_class: "Value",
            catering: "No",
            groundtransfers: "No",
            de_icinginsurance: "No",
            crowdsource: "No",
            way: parsedData.way,
            dateAsText: parsedData.dateAsText,
            timeAsText: parsedData.timeAsText,
         };

         // Round trip: add return flight data
         if (parsedData.way === "round trip") {
            aircraftDetails.returnDateAsText = parsedData.returnDateAsText;
            aircraftDetails.returnTimeAsText = parsedData.timeAsTextReturn;
         }

         // Multi-city: add leg names
         if (parsedData.way === "multi-city") {
            aircraftDetails.fromShortName = parsedData.fromShortName;
            aircraftDetails.toShortName = parsedData.toShortName;
         }

         // Store in sessionStorage
         sessionStorage.setItem(
            "aircraft_details",
            JSON.stringify(aircraftDetails),
         );

         const userEmail = Cookies.get("userEmail");
         const authToken = Cookies.get("authToken");
         const isLoggedIn = userEmail && authToken;

         if (!isLoggedIn) {
            // Show auth forms wrapper and login form if user is not logged in
            authFormsWrapper.style.display = "block";
            loginForm.style.display = "flex";
            return;
         }

         // Check trip classification — show popup for special categories
         const specialCategories = [
            "cargo",
            "group",
            "medevac",
            "helicopter",
            "vip",
         ];
         const currentClassification = tripClassification || "";

         if (specialCategories.includes(currentClassification)) {
            // Show the quote request popup
            initQuotePopup(parsedData);
            return;
         }

         window.location.href = "/checkout";
      });
   });

   paraPopUp.forEach((paraItem) => {
      paraItem.addEventListener("click", function () {
         loginForm.style.display = "flex";
      });
   });

   attachDetailsButtonListeners();
   tabControl();
   submitMessage();
   brokerMesage();
   // initializeSwipers();
   initializeSimpleSliders();
   attachImageClickListeners(); // Attach image click listeners after rendering
   closeSideBar();
   closeDownbar();
   attachItemCheckboxListeners();
   updateCheckedItemsDisplay();

   // Fetch and update hot deal pricing if user is logged in
   if (isLoggedIn && page === 1) {
      updateHotDealPricing();
   }

   document.querySelectorAll(".check-box input").forEach((checkbox) => {
      checkbox.addEventListener("change", function () {
         const checkedItems =
            JSON.parse(sessionStorage.getItem("checkedItems")) || {};

         if (Object.keys(checkedItems).length > 0) {
            document.querySelector(".broker_count").innerHTML = `(${
               Object.keys(checkedItems).length
            })`;
         } else {
            document.querySelector(".broker_count").innerHTML = "(0)";
         }
      });
   });

   document.querySelector(".crosspop").addEventListener("click", function () {
      const checkedItems =
         JSON.parse(sessionStorage.getItem("checkedItems")) || {};
      if (Object.keys(checkedItems).length > 0) {
         document.querySelector(".broker_count").innerHTML = `(${
            Object.keys(checkedItems).length
         })`;
      } else {
         document.querySelector(".broker_count").innerHTML = "(0)";
      }
   });
}

// Function to initialize Swiper sliders
function initializeSwipers() {
   const slideBlocks = document.querySelectorAll(
      "[class*='slide'][class*='block'], [class*='slide'][class*='int']",
   );
   const uniqueIndexes = new Set();
   slideBlocks.forEach((block) => {
      const classes = block.className.split(" ");
      classes.forEach((cl) => {
         const matchBlock = cl.match(/slide(\d+)block/);
         const matchInt = cl.match(/slide(\d+)int/);
         if (matchBlock) {
            uniqueIndexes.add(matchBlock[1]);
         }
         if (matchInt) {
            uniqueIndexes.add(matchInt[1]);
         }
      });
   });

   uniqueIndexes.forEach((sliderClass) => {
      new Swiper(`.slide${sliderClass}block`, {
         slidesPerView: 3,
         loop: true,
         navigation: {
            nextEl: `.nav${sliderClass}next`,
            prevEl: `.nav${sliderClass}prev`,
         },
         spaceBetween: 10,
      });

      new Swiper(`.slide${sliderClass}int`, {
         slidesPerView: 3,
         loop: true,
         navigation: {
            nextEl: `.int${sliderClass}next`,
            prevEl: `.int${sliderClass}prev`,
         },
         spaceBetween: 10,
      });
   });
}

// Function to render pagination controls
function renderPagination(filteredSets) {
   pagination.innerHTML = "";

   const totalPages = Math.ceil(filteredSets.length / itemsPerPage);
   const maxButtonsToShow = 5;
   const startPage = Math.max(
      1,
      currentPage - Math.floor(maxButtonsToShow / 2),
   );
   const endPage = Math.min(totalPages, startPage + maxButtonsToShow - 1);
   const adjustedStartPage = Math.max(1, endPage - maxButtonsToShow + 1);

   const prevButton = document.createElement("button");
   prevButton.classList.add("pagiprev");
   prevButton.disabled = currentPage === 1;
   prevButton.addEventListener("click", () => {
      if (currentPage > 1) {
         currentPage--;
         renderPage(currentPage, filteredSets);
         renderPagination(filteredSets);
      }
   });
   pagination.appendChild(prevButton);

   for (let i = adjustedStartPage; i <= endPage; i++) {
      const button = document.createElement("button");
      button.textContent = i;
      button.className = "pagination-btn";
      if (i === currentPage) button.classList.add("active");
      button.addEventListener("click", () => {
         currentPage = i;
         renderPage(currentPage, filteredSets);
         renderPagination(filteredSets);
      });
      pagination.appendChild(button);
   }

   const nextButton = document.createElement("button");
   nextButton.classList.add("paginext");
   nextButton.disabled = currentPage === totalPages;
   nextButton.addEventListener("click", () => {
      if (currentPage < totalPages) {
         currentPage++;
         renderPage(currentPage, filteredSets);
         renderPagination(filteredSets);
      }
   });
   pagination.appendChild(nextButton);
}

// Function to track aircraft view in klaviyo for logged-in users and also for tatari tracking
function trackAircraftViewInKlaviyo(aircraftData) {
   try {
      // Check if user is logged in
      const userEmail = Cookies.get("userEmail");

      // Use the exact same calculated value from the UI
      const calculatedValue =
         window.aircraftCalculatedValues[aircraftData._id] ||
         Math.round(aircraftData.price_per_hour_fixedrate_number || 0);

      // TATARI TRACKING: Track product view for both logged in and logged out users
      if (typeof tatari !== "undefined") {
         tatari.productViewed({
            name: aircraftData.description_text || "Aircraft",
            price: calculatedValue,
            quantity: 1,
            productId: aircraftData._id || "",
            category: aircraftData.class_text || "Aircraft",
         });
      }

      // Only continue with Klaviyo if user is logged in
      if (!userEmail) {
         return;
      }

      // Prepare aircraft data for Klaviyo
      const item = {
         ProductName: aircraftData.description_text || "Aircraft",
         ProductID: aircraftData._id || "",
         SKU: aircraftData.registration_text || "",
         Categories: aircraftData.class_text || "",
         ImageURL: `https:${aircraftData.exterior_image1_image}`,
         URL: `https://jettly.com/fleet/${aircraftData.Slug}`,
         Brand: aircraftData.operator_txt_text || "",
         Price: calculatedValue,
         CompareAtPrice: calculatedValue,
         Title: aircraftData.description_text || "Aircraft",
         ItemId: aircraftData._id || "",
         Metadata: {
            Brand: aircraftData.operator_txt_text || "",
            Price: calculatedValue,
            CompareAtPrice: calculatedValue,
         },
      };

      // Callback function to track the product view
      function trackProductCallback() {
         if (
            typeof window.klaviyo !== "undefined" &&
            typeof window.klaviyo.track === "function"
         ) {
            window.klaviyo.track("Viewed Product", item);
         }
      }

      // Identify user and track product view using callback (following Klaviyo documentation pattern)
      if (
         typeof window.klaviyo !== "undefined" &&
         typeof window.klaviyo.identify === "function"
      ) {
         window.klaviyo.identify(
            {
               email: userEmail,
            },
            trackProductCallback,
         );
      } else {
         // Fallback: try direct tracking if identify is not available
         trackProductCallback();
      }
   } catch (e) {
      console.error("Failed to track aircraft view", e);
   }
}

// Function to attach event listeners to "View Details" buttons
function attachDetailsButtonListeners() {
   document.querySelectorAll(".details-button").forEach((button) => {
      button.addEventListener("click", function () {
         const btnDataIndex = button.getAttribute("data-index");
         const aircraftId = button.getAttribute("data_got_id");

         // Log the specific aircraft data based on the button's data_got_id
         if (apiData.response && aircraftId) {
            // Find which aircraft set contains the data
            let specificAircraftData = null;
            let foundInSet = null;

            // Dynamically find all aircraft sets in the response
            const aircraftSetKeys = Object.keys(apiData.response).filter(
               (key) =>
                  key.startsWith("aircraft_set_") &&
                  Array.isArray(apiData.response[key]),
            );

            // Check all aircraft sets dynamically
            for (const setKey of aircraftSetKeys) {
               const aircraftSet = apiData.response[setKey];
               if (aircraftSet && aircraftSet.length > 0) {
                  // Find aircraft by _id instead of index
                  specificAircraftData = aircraftSet.find(
                     (aircraft) => aircraft._id === aircraftId,
                  );
                  if (specificAircraftData) {
                     foundInSet = setKey;
                     break;
                  }
               }
            }

            // Also check hot deals if not found in regular aircraft sets
            // if (!specificAircraftData && apiData.response.hot_deal_aircraft) {
            //   specificAircraftData = apiData.response.hot_deal_aircraft.find(
            //     (aircraft) => aircraft._id === aircraftId
            //   );
            //   if (specificAircraftData) {
            //     foundInSet = "hot_deal_aircraft";
            //   }
            // }

            if (specificAircraftData) {
               // Track aircraft view in Klaviyo for logged-in users
               trackAircraftViewInKlaviyo(specificAircraftData);
            }
         }

         document.querySelectorAll(".item_tab_block").forEach((block) => {
            const blockDataIndex = block.getAttribute("data-index");
            if (blockDataIndex === btnDataIndex) {
               block.parentElement.classList.toggle("activeBtn");
               block.classList.toggle("activeTabPanel");
            } else {
               block.classList.remove("activeTabPanel");
               block.parentElement.classList.remove("activeBtn");
            }
         });
      });
   });
}

// Function to control tab visibility
function tabControl() {
   document.querySelectorAll(".item_block_wrapper").forEach((itemWrapper) => {
      const tabItems = itemWrapper.querySelectorAll(
         ".item_tab_heading_block ul .tabxholder li.tiggitem",
      );
      const tabContents = itemWrapper.querySelectorAll(".item_tab_one");
      tabItems.forEach((tabItem) => {
         tabItem.addEventListener("click", function () {
            const tabItemAttr = tabItem.getAttribute("data-item");
            tabItems.forEach((acitem) => {
               acitem.classList.remove("activetabitem");
            });
            tabItem.classList.add("activetabitem");
            tabContents.forEach((tabCnt) => {
               const tabCntAttr = tabCnt.getAttribute("data-cnt");
               if (tabItemAttr === tabCntAttr) {
                  tabCnt.style.display = "block";
               } else {
                  tabCnt.style.display = "none";
               }
            });
         });
      });
   });
}

// close sidebar
function closeSideBar() {
   document.querySelectorAll(".cross_itemx span").forEach((span) => {
      span.addEventListener("click", function () {
         document
            .querySelectorAll(".item_tab_block")
            .forEach((activetabpanel) => {
               activetabpanel.classList.remove("activeTabPanel");
            });
         document.querySelectorAll(".item_block_wrapper").forEach((cross) => {
            cross.classList.remove("activeBtn");
         });
      });
   });
}

// close downbar
function closeDownbar() {
   document.querySelectorAll(".mbcross").forEach((span) => {
      span.addEventListener("click", function () {
         document
            .querySelectorAll(".item_tab_block")
            .forEach((activetabpanel) => {
               activetabpanel.classList.remove("activeTabPanel");
            });
         document.querySelectorAll(".item_block_wrapper").forEach((cross) => {
            cross.classList.remove("activeBtn");
         });
      });
   });
}

// Function to handle message form submissions
function submitMessage() {
   const messageForms = document.querySelectorAll(".askform form");
   messageForms.forEach((formBox) => {
      formBox.addEventListener("submit", async (e) => {
         e.preventDefault();
         const message = e.target[0].value;
         const operatorId = e.target[1].value;
         const payload = {
            operator_id: operatorId,
            flight_request_id: flightRequestId,
            message_text: message,
         };
         try {
            const response = await fetch(
               "https://operators-dashboard.bubbleapps.io/api/1.1/wf/send_message",
               {
                  method: "POST",
                  headers: {
                     "Content-Type": "application/json",
                  },
                  body: JSON.stringify(payload),
               },
            );
            if (response.ok) {
               alert("Message sent successfully.");
               e.target.reset(); // Reset the form after successful submission
            } else {
               alert("Failed to send message.");
            }
         } catch (error) {
            alert("Error occurred while sending message.");
         }
      });
   });
}

function brokerMesage() {
   const brokerSubmitBtn = document.querySelector(".consubtn");

   // Remove any existing event listeners to prevent multiple alerts
   brokerSubmitBtn.removeEventListener("click", handleBrokerSubmit);
   brokerSubmitBtn.addEventListener("click", handleBrokerSubmit);
}

async function handleBrokerSubmit() {
   const brokerMessagetext = document.querySelector(
      ".contact_text textarea",
   ).value;
   const checkedItems =
      JSON.parse(sessionStorage.getItem("checkedItems")) || {};
   const aircraftIds = Object.keys(checkedItems);
   const requestData = {
      aircraftids: aircraftIds,
      message: brokerMessagetext,
   };

   if (!brokerMessagetext || aircraftIds.length < 1) {
      alert("Please enter a message or select an aircraft.");
      return;
   } else {
      try {
         const response = await fetch(
            "https://operators-dashboard.bubbleapps.io/api/1.1/wf/broker_request",
            {
               method: "POST",
               headers: {
                  "Content-Type": "application/json",
               },
               body: JSON.stringify(requestData),
            },
         );
         const data = await response.json();
         alert("Message sent successfully.");
      } catch (error) {
         console.error("Error:", error);
      }
   }
}

// Call the function to set up the event listener
brokerMesage();

function attachItemCheckboxListeners() {
   document
      .querySelectorAll('.broker_checkbox input[type="checkbox"]')
      .forEach((checkbox) => {
         const uniqueId = checkbox.getAttribute("data-id");
         if (uniqueId) {
            // Ensure checkbox reflects the state
            checkbox.checked = checkedItems[uniqueId] || false;

            // Add event listener to update checkedItems
            checkbox.addEventListener("change", (e) => {
               if (e.target.checked) {
                  checkedItems[uniqueId] = true;
               } else {
                  delete checkedItems[uniqueId];
                  // If the popup is open, remove the corresponding item
                  const popupCheckbox = document.querySelector(
                     `#selectedItemsContainer .broker_checkbox input[data-id="${uniqueId}"]`,
                  );
                  if (popupCheckbox) {
                     popupCheckbox.checked = false;
                     popupCheckbox.closest(".broker_mode_cnt").remove();
                  }
               }
               // Persist the state to sessionStorage
               sessionStorage.setItem(
                  "checkedItems",
                  JSON.stringify(checkedItems),
               );
               // Update the display div
               updateCheckedItemsDisplay();
            });
         }
      });
}

// Function to update the display div with checked items
function attachItemCheckboxListeners() {
   document
      .querySelectorAll('.broker_checkbox input[type="checkbox"]')
      .forEach((checkbox) => {
         const uniqueId = checkbox.getAttribute("data-id");
         if (uniqueId) {
            // Ensure checkbox reflects the state
            checkbox.checked = checkedItems[uniqueId] || false;

            // Add event listener to update checkedItems
            checkbox.addEventListener("change", (e) => {
               if (e.target.checked) {
                  checkedItems[uniqueId] = true;
               } else {
                  delete checkedItems[uniqueId];
               }
               // Persist the state to sessionStorage
               sessionStorage.setItem(
                  "checkedItems",
                  JSON.stringify(checkedItems),
               );
               // Update the display div
               updateCheckedItemsDisplay();
            });
         }
      });
}

// Function to generate HTML for Hot Deal items
function getHotDealHtml(
   item,
   index,
   calculateTotal,
   totalHours,
   totalMinutes,
   stopInfo,
   allImageExt,
   allImageInt,
   checkExtLength,
   checkIntLength,
   words,
   apiData,
   intabWrapper,
   calculateHoursRate,
   uniqueId,
   isChecked,
) {
   const operatorAddress =
      item.base_airport_fixed_address_geographic_address?.address ||
      "Address not available";

   // Create a new array with both exterior and interior images
   const allImages = [item.exterior_image1_image];
   if (item.interior_image1_image) {
      allImages.push(item.interior_image1_image);
   }
   return `
    <div class="item_wrapper">
      <div class="hot_headls_logo">
        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67679deeedb869e511e6778f_6752921836657f93c6cd2590_hotlogo.png" alt="Hot Deal Logo" />
        <span>Hot <br /> Deal </span>
      </div>
      <div class="item_img slider-container" id="slider-${index}">
        ${allImages
           .map(
              (imgSrc, imgIndex) => `
          <div class="slide ${imgIndex === 0 ? "active" : ""}">
            <div class="dyslideItem">
              <img src="${imgSrc}" alt="Aircraft Image ${imgIndex + 1}" />
            </div>
          </div>
        `,
           )
           .join("")}
        <button class="prev-btn" data-slider-id="slider-${index}">&lt;</button>
        <button class="next-btn" data-slider-id="slider-${index}">&gt;</button>
      </div>

      <div class="item_cnt">
        <h4>${item.description_text}</h4>
        <p> and similar ${
           item.class_text
        }s <br /> <img class="seat_logo" src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/674f4ca8521e970e24495468_seat.png" alt="Seat Icon" />
          <span>Up to ${item.pax_number}</span> seats
        </p>
        <div class="hot_feature">
          <p>
            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67528f529e24322ef8d71586_check.png" alt="Check Icon" />INSTANT BOOKING
          </p>
          <p>
            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67528f529e24322ef8d71586_check.png" alt="Check Icon" />GUARANTEED PRICE
          </p>
          <p>
            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67528f529e24322ef8d71586_check.png" alt="Check Icon" />GUARANTEED AVAILABILITY
          </p>
          <p>
            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67528f529e24322ef8d71586_check.png" alt="Check Icon" />EXCLUSIVE TO JET CARD HOLDERS
          </p>
        </div>
      </div>
      <div class="item_book hot_book">
        <div class="itemstop">
          <div class="entire">
            <p>${item.description_text}. Entire aircraft</p>
          </div>
        </div>
        <p class="view_price_tologin">LOGIN TO VIEW PRICING</p>
        <div class="price" data-hot-deal-category="${
           item.instant_book_hot_deal_category_text || ""
        }" data-item-id="${item._id}">
          <h3 class="main_price"><img style="width: 100px;" src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/691376b3a1d1243d2e443b61_animation.gif" alt="" /></h3>
          <h5 class="hourly_rate"></h5>
          <p>Final Price + Tax at Checkout</p>
        </div>
        <div class="bookingbutton">
<a  class="bookinglink button fill_button request-book-btn" href="#"  data-flightrequestid="${flightRequestId}" data-type="instant" data-aircraftid="${
      item._id
   }">BOOK INSTANTLY</a>
          <button data_got_id="${
             item._id
          }" class="details-button button fill_button grey_button" data-index="${index}">View Details <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67459d1f63b186d24efc3bbe_Jettly-Search-Results-Page-(List-View-Details-Tab).png" alt="View Details Icon" />
          </button>
        </div>
      </div>
    </div>
    <div class="item_tab_block" data-index="${index}">
      <div class="overflow_wrapper">
      <div class="cross_mb_icon">
        <div class="item_tab_heading_block">
          <div class="cross_itemx">
            <span><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6767c563264061ca37171a7c_x-square.svg" alt="" /></span>
          </div>
          <ul>
            <div class="tabxholder"><li class="activetabitem tiggitem" data-item="tab${index}img">Images</li>
              <!-- Images Tab -->
              <div data-cnt="tab${index}img" class="item_tab_one tabitem_inline" style="display: block">
                <div class="tab_one_heading">
                  <h3>${item.class_text} Exteriors</h3>
                  <p>Note: The images depicted are examples of ${
                     item.class_text
                  }s and may not represent the specific aircraft you will be flying on.</p>
                </div>
                <div class="tab_one_slider ${
                   checkExtLength <= 3 ? "sliderOn" : ""
                }">
                  <div class="swiper slide${index}block">
                    <div class="swiper-wrapper"> ${allImageExt} </div>
                  </div>
                  <div class="swipper_ctrl">
                    <span class="nav${index}prev">
                      <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
                    </span>
                    <span class="nav${index}next">
                      <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
                    </span>
                  </div>
                </div>
                <div class="tab_one_heading tab_one_next_heading">
                  <h3>${item.class_text} Interiors</h3>
                  <p>Note: The images depicted are examples of ${
                     item.class_text
                  }s and may not represent the specific aircraft you will be flying on.</p>
                </div>
                <div class="tab_one_slider ${
                   checkIntLength <= 3 ? "sliderOn" : ""
                }">
                  <div class="swiper slide${index}int">
                    <div class="swiper-wrapper"> ${allImageInt} </div>
                  </div>
                  <div class="swipper_ctrl">
                    <span class="int${index}prev">
                      <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
                    </span>
                    <span class="int${index}next">
                      <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
                    </span>
                  </div>
                </div>
              </div>
            </div>            
            <div class="tabxholder"><li class="tiggitem" data-item="tab${index}det">Details</li>
              <!-- Details Tab -->
              <div data-cnt="tab${index}det" class="item_tab_one">
                <div class="detailstb_wrapper">
                  <div class="detailstb_left">
                    <h3>Details</h3>
                    <div class="detailstb_left_det">
                      <div class="detailstb_left_det_item">
                        <p>Class:</p>
                        <p>${item.class_text}</p>
                      </div>
                      <div class="detailstb_left_det_item">
                        <p>Max Passengers:</p>
                        <p>${item.pax_number}</p>
                      </div>
                      <div class="detailstb_left_det_item">
                        <p>Year of Make:</p>
                        <p>${item.year_of_manufacture_number}</p>
                      </div>
                      <div class="detailstb_left_det_item">
                        <p>Wyvern Safety Rated:</p>
                        <p>${item.wyvern_rating_text}</p>
                      </div>
                      <div class="detailstb_left_det_item">
                        <p>ARG/US Safety Rating:</p>
                        <p>${item.argus_us_rating_text}</p>
                      </div>
                      ${
                         item.insured_amount_number > 0
                            ? `
                            <div class="detailstb_left_det_item">
                              <p>Liability Insurance:</p>
                              <p>$${item.insured_amount_number.toLocaleString()}</p>
                            </div>
                          `
                            : ""
                      }
                    </div>
                  </div>
                  <div class="detailstb_left detailstb_right">
                    <h3>Amenities</h3>
                    <div class="detailstb_left_det">
                      ${words}
                    </div>
                  </div>
                </div>
              </div>
            </div>            
            <div class="tabxholder"><li class="tiggitem" data-item="tab${index}it">Itinerary</li>
              <!-- Itinerary Tab -->
              <div data-cnt="tab${index}it" class="item_tab_one">
                <div class="inttabDet">
                  <h3>Flight Legs</h3>
                  ${intabWrapper}
                </div>
              </div>     
            </div>            
            <div class="tabxholder"><li class="tiggitem" data-item="tab${index}op">Operator</li>
              <!-- Operators Tab -->
              <div data-cnt="tab${index}op" class="item_tab_one">
                <div class="opadetails">
                  <h3>Operator</h3>
                  <div class="opadet_wrapper">
                    <div class="opadet_top">
                      <div class="opadet_top_left">
                        <p>${item.operator_txt_text}</p>
                        <img src="${
                           item.operator_logo_image
                        }" alt="Operator Logo" />
                      </div>
                      <div class="opadet_top_middle">
                        <p><span>Response Rate:</span> 100%</p>
                        <p><span>Avg. Response Time:</span> &lt;1 Hrs.</p>
                        <p><span>Aircraft:</span> 2</p>
                        <p><span>Address:</span> ${operatorAddress}</p>
                        <p><span>Hours:</span> 24 Hours</p>
                        <p><span>Certificate ID:</span> Ask us</p>
                      </div>
                      <div class="opadet_top_right">
  <iframe
  src="https://www.google.com/maps/embed/v1/place?key=AIzaSyALUxYUzfuMmECXI_q_it5VBehlUCE_Ml8&q=${encodeURIComponent(
     operatorAddress,
  )}"
  frameborder="0"
  style="border:0;"
  allowfullscreen=""
  loading="lazy">
</iframe>

</div>
                    </div>
                    <div class="opadet_bottom">
                      <div class="opadet_bottom_heading">
                        <ul>
                          <li><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754085d1d9a01ce66e3a259_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Icon" /></li>
                          <li>0.00 | 0</li>
                          <li><span>Reviews</span></li>
                        </ul>
                      </div>
                      <div class="opadet_bottom_review">
                        <div class="opadet_bottom_review_left">
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>5 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>4 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>3 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>2 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>1 Star</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                        </div>
                        <div class="opadet_bottom_review_right">
                          <h3>Rating Breakdown</h3>
                          <div class="opadet_bottom_review_right_item">
                            <p>Seller communication level <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                            <p>Recommended to other passengers <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                            <p>Service as described <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                            <p>Flight cancellation rate <span>0% <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>              
                </div>
              </div>
              <!-- Operators Tab End -->
            </div>            
            <div class="tabxholder"><li class="tiggitem" data-item="tab${index}pl">Policies</li>
              <!-- Policies Tab -->
              <div data-cnt="tab${index}pl" class="item_tab_one">
                <div class="poli_wrapper">
                  <h3>Available Fare Classes</h3>  
                  <div class="poli_box_wrapper">
                    <!-- Value Fare Class -->
                    <div class="polibox">
                      <div class="polibox_heading">
                        <h3>Value <span>+ $0</span></h3>                              
                      </div>
                      <div class="polibox_cnt">
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>$95 Change Fee:</span> Applies to all flight modifications.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>Non-Refundable:</span> Flight fare is non-refundable for client-initiated cancellations.</p>
                        </div>
                      </div>
                    </div>
                    <!-- Flex Fare Class -->
                    <div class="polibox polibox_two">
                      <div class="polibox_heading">
                        <h3>Flex <span>+ 5%</span></h3>
                        <span class="recom">Recommended</span>                              
                      </div>
                      <div class="polibox_cnt">
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>No Change Fee</span></p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>No Fee:</span> Cancel more than 336 hours (14 days) before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>50% Fee:</span> Cancel 96 – 336 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>Cancellations refunded in Jettly flight credits only</span></p>
                        </div>
                      </div>
                    </div>
                    <div class="polibox">
                      <div class="polibox_heading">
                        <h3>Premium <span>+ 10%</span></h3>
                      </div>
                      <div class="polibox_cnt">
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>No Change Fee</span></p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>No Fee:</span> Cancel more than 168 hours (7 days) before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>50% Fee:</span> Cancel 96 – 168 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>Cancellations refunded to original payment method or in Jettly flight credits</span></p>
                        </div>
                      </div>
                    </div>
                  </div>  
                </div>
              </div>
              <!-- Policies Tab End -->
            </div>            
            <div class="tabxholder"><li class="tiggitem" data-item="tab${index}py">Payments</li>
              <!-- Payments Tab -->
              <div data-cnt="tab${index}py" class="item_tab_one">
                <div class="payment_tab">
                  <h3>Payments</h3>
                  <div class="payment_wrapper">
                    <div class="paymenttab_left">
                      <div class="paymenttab_left_item">
                        <div class="paymenttab_item_img">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p>Pay in full upon aircraft availability confirmation by ${
                           item.operator_txt_text
                        }</p>
                      </div>
                      <div class="paymenttab_left_item">
                        <div class="paymenttab_item_img">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p>Acceptable payment methods: Visa, MasterCard, American Express, Wire, ACH, Cryptocurrency</p>
                      </div>
                      <div class="paymenttab_left_item">
                        <div class="paymenttab_item_img">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p>You will receive an invoice for the trip once the aircraft is confirmed</p>
                      </div>
                    </div>
                    <div class="paymenttab_right">
                      <p>Upon Confirmation</p>
                      <div class="paymenttab_right_percent">
                        <div class="paybar"></div>
                        <div class="paybar_text">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          <span>100%</span>
                        </div>
                      </div>
                      <p>Pay in full once the aircraft is confirmed available by ${
                         item.operator_txt_text
                      }.</p>
                      <div class="payment">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755a86f952bce124bed0a9d_payment.png" alt="Payment Methods" />
                      </div>
                    </div>
                  </div>
                </div>
              </div><!-- Payments Tab End -->
            </div>            
            <div class="tabxholder"><li class="tiggitem" data-item="tab${index}ask">Ask Us a Question</li>
              <!-- Ask Us a Question Tab -->
              <div data-cnt="tab${index}ask" class="item_tab_one">
                <div class="payment_tab">
                  <h3>Message ${item.operator_txt_text}</h3>
                  <div class="payment_wrapper askform">
                    <form>
                      <textarea required placeholder="Type your message here"></textarea>
                      <input type="hidden" value="${
                         item.managed_a_c_operator_custom_managed_air_operator
                      }" />
                      <div class="submitbtn">
                        <button type="submit"><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755b3a876accbd14f83880f_plan.png" alt="Send Message Icon" /></button>
                      </div>
                    </form>
                  </div>
                </div>
              </div>
              <!-- Ask Us a Question Tab End -->
            </div>            
          </ul> 
          <img class="mbcross" src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6769a03a6c10d465500c1cff_cross.png" alt="" />         
        </div>        
        </div>
        <div class="tab_item_cnt_wrapper">
          <!-- Images Tab -->
          <div data-cnt="tab${index}img" class="item_tab_one">
            <div class="tab_one_heading">
              <h3>${item.class_text} Exteriors</h3>
              <p>Note: The images depicted are examples of ${
                 item.class_text
              }s and may not represent the specific aircraft you will be flying on.</p>
            </div>
            <div class="tab_one_slider ${
               checkExtLength <= 3 ? "sliderOn" : ""
            }">
              <div class="swiper slide${index}block">
                <div class="swiper-wrapper"> ${allImageExt} </div>
              </div>
              <div class="swipper_ctrl">
                <span class="nav${index}prev">
                  <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
                </span>
                <span class="nav${index}next">
                  <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
                </span>
              </div>
            </div>
            <div class="tab_one_heading tab_one_next_heading">
              <h3>${item.class_text} Interiors</h3>
              <p>Note: The images depicted are examples of ${
                 item.class_text
              }s and may not represent the specific aircraft you will be flying on.</p>
            </div>
            <div class="tab_one_slider ${
               checkIntLength <= 3 ? "sliderOn" : ""
            }">
              <div class="swiper slide${index}int">
                <div class="swiper-wrapper"> ${allImageInt} </div>
              </div>
              <div class="swipper_ctrl">
                <span class="int${index}prev">
                  <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
                </span>
                <span class="int${index}next">
                  <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
                </span>
              </div>
            </div>
          </div>

          <!-- Details Tab -->
          <div data-cnt="tab${index}det" class="item_tab_one">
            <div class="detailstb_wrapper">
              <div class="detailstb_left">
                <h3>Details</h3>
                <div class="detailstb_left_det">
                  <div class="detailstb_left_det_item">
                    <p>Class:</p>
                    <p>${item.class_text}</p>
                  </div>
                  <div class="detailstb_left_det_item">
                    <p>Max Passengers:</p>
                    <p>${item.pax_number}</p>
                  </div>
                  <div class="detailstb_left_det_item">
                    <p>Year of Make:</p>
                    <p>${item.year_of_manufacture_number}</p>
                  </div>
                  <div class="detailstb_left_det_item">
                    <p>Wyvern Safety Rated:</p>
                    <p>${item.wyvern_rating_text}</p>
                  </div>
                  <div class="detailstb_left_det_item">
                    <p>ARG/US Safety Rating:</p>
                    <p>${item.argus_us_rating_text}</p>
                  </div>
                  ${
                     item.insured_amount_number > 0
                        ? `
                        <div class="detailstb_left_det_item">
                          <p>Liability Insurance:</p>
                          <p>$${item.insured_amount_number.toLocaleString()}</p>
                        </div>
                      `
                        : ""
                  }
                </div>
              </div>
              <div class="detailstb_left detailstb_right">
                <h3>Amenities</h3>
                <div class="detailstb_left_det">
                  ${words}
                </div>
              </div>
            </div>
          </div>

          <!-- Itinerary Tab -->
          <div data-cnt="tab${index}it" class="item_tab_one">
            <div class="inttabDet">
              <h3>Flight Legs</h3>
              ${intabWrapper}
            </div>
          </div>

          <!-- Operators Tab -->
          <div data-cnt="tab${index}op" class="item_tab_one">
            <div class="opadetails">
              <h3>Operator</h3>
              <div class="opadet_wrapper">
                <div class="opadet_top">
                  <div class="opadet_top_left">
                    <p>${item.operator_txt_text}</p>
                    <img src="${
                       item.operator_logo_image
                    }" alt="Operator Logo" />
                  </div>
                  <div class="opadet_top_middle">
                    <p><span>Response Rate:</span> 100%</p>
                    <p><span>Avg. Response Time:</span> &lt;1 Hrs.</p>
                    <p><span>Aircraft:</span> 2</p>
                    <p><span>Address:</span> ${operatorAddress}</p>
                    <p><span>Hours:</span> 24 Hours</p>
                    <p><span>Certificate ID:</span> Ask us</p>
                  </div>
                  <div class="opadet_top_right">
                    <iframe
  src="https://www.google.com/maps/embed/v1/place?key=AIzaSyALUxYUzfuMmECXI_q_it5VBehlUCE_Ml8&q=${encodeURIComponent(
     operatorAddress,
  )}"
  frameborder="0"
  style="border:0;"
  allowfullscreen=""
  loading="lazy">
</iframe>

                  </div>
                </div>
                <div class="opadet_bottom">
                  <div class="opadet_bottom_heading">
                    <ul>
                      <li><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754085d1d9a01ce66e3a259_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Icon" /></li>
                      <li>0.00 | 0</li>
                      <li><span>Reviews</span></li>
                    </ul>
                  </div>
                  <div class="opadet_bottom_review">
                    <div class="opadet_bottom_review_left">
                      <div class="reviewitem_block">
                        <div class="obarleft">
                          <p>5 Stars</p>
                        </div>
                        <div class="obarmiddle">
                          <span></span>
                        </div>
                        <div class="obaright">
                          <p>(0)</p>
                        </div>
                      </div>
                      <div class="reviewitem_block">
                        <div class="obarleft">
                          <p>4 Stars</p>
                        </div>
                        <div class="obarmiddle">
                          <span></span>
                        </div>
                        <div class="obaright">
                          <p>(0)</p>
                        </div>
                      </div>
                      <div class="reviewitem_block">
                        <div class="obarleft">
                          <p>3 Stars</p>
                        </div>
                        <div class="obarmiddle">
                          <span></span>
                        </div>
                        <div class="obaright">
                          <p>(0)</p>
                        </div>
                      </div>
                      <div class="reviewitem_block">
                        <div class="obarleft">
                          <p>2 Stars</p>
                        </div>
                        <div class="obarmiddle">
                          <span></span>
                        </div>
                        <div class="obaright">
                          <p>(0)</p>
                        </div>
                      </div>
                      <div class="reviewitem_block">
                        <div class="obarleft">
                          <p>1 Star</p>
                        </div>
                        <div class="obarmiddle">
                          <span></span>
                        </div>
                        <div class="obaright">
                          <p>(0)</p>
                        </div>
                      </div>
                    </div>
                    <div class="opadet_bottom_review_right">
                      <h3>Rating Breakdown</h3>
                      <div class="opadet_bottom_review_right_item">
                        <p>Seller communication level <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                        <p>Recommended to other passengers <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                        <p>Service as described <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                        <p>Flight cancellation rate <span>0% <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>              
            </div>
          </div>
          <!-- Operators Tab End -->
          <!-- Policies Tab -->
              <div data-cnt="tab${index}pl" class="item_tab_one">
                <div class="poli_wrapper">
                  <h3>Available Fare Classes</h3>  
                  <div class="poli_box_wrapper">
                    <!-- Value Fare Class -->
                    <div class="polibox">
                      <div class="polibox_heading">
                        <h3>Value <span>+ $0</span></h3>                              
                      </div>
                      <div class="polibox_cnt">
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>$95 Change Fee:</span> Applies to all flight modifications.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>Non-Refundable:</span> Flight fare is non-refundable for client-initiated cancellations.</p>
                        </div>
                      </div>
                    </div>
                    <!-- Flex Fare Class -->
                    <div class="polibox polibox_two">
                      <div class="polibox_heading">
                        <h3>Flex <span>+ 5%</span></h3>
                        <span class="recom">Recommended</span>                              
                      </div>
                      <div class="polibox_cnt">
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>No Change Fee</span></p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>No Fee:</span> Cancel more than 336 hours (14 days) before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>50% Fee:</span> Cancel 96 – 336 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>Cancellations refunded in Jettly flight credits only</span></p>
                        </div>
                      </div>
                    </div>
                    <div class="polibox">
                      <div class="polibox_heading">
                        <h3>Premium <span>+ 10%</span></h3>
                      </div>
                      <div class="polibox_cnt">
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>No Change Fee</span></p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>No Fee:</span> Cancel more than 168 hours (7 days) before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p><span>50% Fee:</span> Cancel 96 – 168 hours before departure.</p>
                        </div>
                        <div class="polibox_cnt_item">
                          <div class="checkicon">
                            <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          </div>
                          <p class="capitalize"><span>Cancellations refunded to original payment method or in Jettly flight credits</span></p>
                        </div>
                      </div>
                    </div>
                  </div>  
                </div>
              </div>
              <!-- Policies Tab End -->
              <!-- Payments Tab -->
              <div data-cnt="tab${index}py" class="item_tab_one">
                <div class="payment_tab">
                  <h3>Payments</h3>
                  <div class="payment_wrapper">
                    <div class="paymenttab_left">
                      <div class="paymenttab_left_item">
                        <div class="paymenttab_item_img">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p>Pay in full upon aircraft availability confirmation by ${
                           item.operator_txt_text
                        }</p>
                      </div>
                      <div class="paymenttab_left_item">
                        <div class="paymenttab_item_img">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p>Acceptable payment methods: Visa, MasterCard, American Express, Wire, ACH, Cryptocurrency</p>
                      </div>
                      <div class="paymenttab_left_item">
                        <div class="paymenttab_item_img">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p>You will receive an invoice for the trip once the aircraft is confirmed</p>
                      </div>
                    </div>
                    <div class="paymenttab_right">
                      <p>Upon Confirmation</p>
                      <div class="paymenttab_right_percent">
                        <div class="paybar"></div>
                        <div class="paybar_text">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                          <span>100%</span>
                        </div>
                      </div>
                      <p>Pay in full once the aircraft is confirmed available by ${
                         item.operator_txt_text
                      }.</p>
                      <div class="payment">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755a86f952bce124bed0a9d_payment.png" alt="Payment Methods" />
                      </div>
                    </div>
                  </div>
                </div>
              </div><!-- Payments Tab End -->
              <!-- Ask Us a Question Tab -->
              <div data-cnt="tab${index}ask" class="item_tab_one">
                <div class="payment_tab">
                  <h3>Message ${item.operator_txt_text}</h3>
                  <div class="payment_wrapper askform">
                    <form>
                      <textarea required placeholder="Type your message here"></textarea>
                      <input type="hidden" value="${
                         item.managed_a_c_operator_custom_managed_air_operator
                      }" />
                      <div class="submitbtn">
                        <button type="submit"><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755b3a876accbd14f83880f_plan.png" alt="Send Message Icon" /></button>
                      </div>
                    </form>
                  </div>
                </div>
              </div>
              <!-- Ask Us a Question Tab End -->
        </div>
      </div>
      `;
}

// Function to generate HTML for Regular items
function getRegularItemHtml(
   item,
   index,
   calculateTotal,
   totalHours,
   totalMinutes,
   stopInfo,
   allImageExt,
   allImageInt,
   checkExtLength,
   checkIntLength,
   words,
   apiData,
   intabWrapper,
   calculateHoursRate,
   uniqueId,
   isChecked,
   isOnRequest,
) {
   const operatorAddress =
      item.base_airport_fixed_address_geographic_address?.address ||
      "Address not available";

   // Create a new array with both exterior and interior images
   const allImages = [item.exterior_image1_image];
   if (item.interior_image1_image) {
      allImages.push(item.interior_image1_image);
   }

   const legReverse = Array.isArray(apiData.response.flight_legs)
      ? [...apiData.response.flight_legs].reverse()
      : [];

   const legCruiseSpeed = item.cruise_speed_avg_fixedrate_number || 0;
   const legStumolatedNumber =
      legCruiseSpeed > 0
         ? legReverse[0].total_distance__statute_m__number / legCruiseSpeed
         : 0;

   const legHours = Math.floor(legStumolatedNumber);
   const legMin = Math.floor((legStumolatedNumber - legHours) * 60);
   const legFormattedTime = isOnRequest
      ? "On Request"
      : `${legHours} H ${legMin} M`;

   const decimalTime = isOnRequest ? "-" : `${legHours}.${legMin}`;

   return `
      
      <div class="item_wrapper">
        <div class="broker_mode_cnt">
          <div class="broker_item details-button" data-index="${index}">
            <div class="broker_item_img_wrapper">
              <div class="broker_item_img">
                <img src="${item.exterior_image1_image}" alt="" />
              </div>
              <div class="broker_item_para">
                <p>${item.description_text}</p>
              </div>
            </div>
            <div class="broker_pax">
              <p>${item.pax_number}</p>
            </div>
            <div class="broker_pax">
              <p>${item.year_of_manufacture_number}</p>
            </div>
            <div class="broker_pax">
              <p>${decimalTime}</p>
            </div>
            <div class="broker_pax" style="display: none">
              <p>2.52 KMKE</p>
            </div>
            <div class="broker_pax">
              <p>${item.operator_txt_text}</p>
            </div>
            <div class="broker_pax brokerprice_mode">
              <p>${isOnRequest ? "On Request" : `$ ${calculateTotal}`}</p>
            </div>
          </div>
          <div class="broker_checkbox">
            <label class="check-box">
              <input autocomplete="off" type="checkbox" data-id="${uniqueId}" ${
                 isChecked ? "checked" : ""
              } />
              <span class="checkmark"></span>
            </label>            
          </div>
        </div>        
        <div class="item_img slider-container" id="slider-${index}">
          ${allImages
             .map(
                (imgSrc, imgIndex) => `
            <div class="slide ${imgIndex === 0 ? "active" : ""}">
              <div class="dyslideItem">
                <img src="${imgSrc}" alt="Aircraft Image ${imgIndex + 1}" />
              </div>
            </div>
          `,
             )
             .join("")}
          <button class="prev-btn" data-slider-id="slider-${index}">&lt;</button>
          <button class="next-btn" data-slider-id="slider-${index}">&gt;</button>
        </div>
        <div class="item_cnt">
          <h4>${item.description_text}</h4>
          <p>${
             item.class_text
          } <br /> <img class="seat_logo" src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/674f4ca8521e970e24495468_seat.png" alt="Seat Icon" />
            <span>${item.pax_number}</span> seats
          </p>
          <img class="operatorlogo" src="${
             item.operator_logo_image
          }" alt="Operator Logo" />
        </div>
        <div class="item_book">
          <div class="destination_flight">
            <div class="portcodename">
              <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/674f7273cb8e26b728b6fdd7_plan-road.png" alt="Plan Road Icon" />
            </div>
          </div>
          <div class="itemstop">
            <div class="itemstop_left">
              <p>${apiData.response.departure_main_code}</p>
            </div>
            <div class="itemstop_middle"${isOnRequest ? ' style="display: none;"' : ""}>
              <p>${stopInfo}</p>
              <span>|</span>
              <p>${legFormattedTime}</p>
            </div>
            <div class="itemstop_left">
              <p>${apiData.response.arrival_main_code}</p>
            </div>
          </div>
          <p class="view_price_tologin${isOnRequest ? " on-request" : ""}">LOGIN TO VIEW PRICING</p>
          <div class="price${isOnRequest ? " on-request" : ""}">
            <h3>${isOnRequest ? "Pricing On Request" : `$${calculateTotal}`}</h3>
           ${isOnRequest ? "" : `<h5>$${Math.round(calculateHoursRate).toLocaleString()}/hr</h5>`}
            <p>${isOnRequest ? "Tailored quotes. No obligations." : "+ Taxes at checkout • Positioning costs\u00a0may\u00a0apply"}</p>
          </div>
          <div class="bookingbutton">
            <a  class="bookinglink button fill_button request-book-btn" href="#"  data-flightrequestid="${flightRequestId}" data-type="market" data-aircraftid="${
               item._id
            }">REQUEST TO BOOK</a>
            <button data_got_id="${item._id}" data-calculated-price="${
               isOnRequest ? 0 : parseInt(calculateTotal.replace(/,/g, ""), 10)
            }" class="details-button button fill_button grey_button" data-index="${index}">View Details <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67459d1f63b186d24efc3bbe_Jettly-Search-Results-Page-(List-View-Details-Tab).png" alt="View Details Icon" />
            </button>
          </div>
        </div>
      </div>
      <div class="item_tab_block" data-index="${index}">
        <div class="overflow_wrapper">
        <div class="cross_mb_icon">        
          <div class="item_tab_heading_block">
          <div class="cross_itemx">
            <span><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6767c563264061ca37171a7c_x-square.svg" alt="" /></span>
          </div>
        <ul>
          <div class="tabxholder"><li class="activetabitem tiggitem" data-item="tab${index}img">Images</li>
            <!-- Images Tab -->
            <div data-cnt="tab${index}img" class="item_tab_one tabitem_inline" style="display:block;">
              <div class="tab_one_heading">
                <h3>EXTERIOR IMAGES</h3>
              </div>
              <div class="tab_one_slider ${
                 checkExtLength <= 3 ? "sliderOn" : ""
              }">
                <div class="swiper slide${index}block">
                  <div class="swiper-wrapper"> ${allImageExt} </div>
                </div>
                <div class="swipper_ctrl">
                  <span class="nav${index}prev">
                    <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
                  </span>
                  <span class="nav${index}next">
                    <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
                  </span>
                </div>
              </div>
              <div class="tab_one_heading tab_one_next_heading">
                <h3>INTERIOR IMAGES</h3>
              </div>
              <div class="tab_one_slider ${
                 checkIntLength <= 3 ? "sliderOn" : ""
              }">
                <div class="swiper slide${index}int">
                  <div class="swiper-wrapper"> ${allImageInt} </div>
                </div>
                <div class="swipper_ctrl">
                  <span class="int${index}prev">
                    <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
                  </span>
                  <span class="int${index}next">
                    <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div class="tabxholder"><li class="tiggitem" data-item="tab${index}det">Details</li>
            <!-- Details Tab -->
            <div data-cnt="tab${index}det" class="item_tab_one">
              <div class="detailstb_wrapper">
                <div class="detailstb_left">
                  <h3>Details</h3>
                  <div class="detailstb_left_det">
                    <div class="detailstb_left_det_item">
                      <p>Class:</p>
                      <p>${item.class_text}</p>
                    </div>
                    <div class="detailstb_left_det_item">
                      <p>Max Passengers:</p>
                      <p>${item.pax_number}</p>
                    </div>
                    <div class="detailstb_left_det_item">
                      <p>Year of Make:</p>
                      <p>${item.year_of_manufacture_number}</p>
                    </div>
                    <div class="detailstb_left_det_item">
                      <p>Wyvern Safety Rated:</p>
                      <p>${item.wyvern_rating_text}</p>
                    </div>
                    <div class="detailstb_left_det_item">
                      <p>ARG/US Safety Rating:</p>
                      <p>${item.argus_us_rating_text}</p>
                    </div>
                    ${
                       item.insured_amount_number > 0
                          ? `
                          <div class="detailstb_left_det_item">
                            <p>Liability Insurance:</p>
                            <p>$${item.insured_amount_number.toLocaleString()}</p>
                          </div>
                        `
                          : ""
                    }
                  </div>
                </div>
                <div class="detailstb_left detailstb_right">
                  <h3>Amenities</h3>
                  <div class="detailstb_left_det">
                    ${words}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="tabxholder"><li class="tiggitem" data-item="tab${index}it">Itinerary</li>
            <!-- Itinerary Tab -->
              <div data-cnt="tab${index}it" class="item_tab_one">
                <div class="inttabDet">
                  <h3>Flight Legs</h3>
                  ${intabWrapper}
                </div>
              </div> 
          </div>
          <div class="tabxholder"><li class="tiggitem" data-item="tab${index}op">Operator</li>
              <!-- Operators Tab -->
              <div data-cnt="tab${index}op" class="item_tab_one">
                <div class="opadetails">
                  <h3>Operator</h3>
                  <div class="opadet_wrapper">
                    <div class="opadet_top">
                      <div class="opadet_top_left">
                        <p>${item.operator_txt_text}</p>
                        <img src="${
                           item.operator_logo_image
                        }" alt="Operator Logo" />
                      </div>
                      <div class="opadet_top_middle">
                        <p><span>Response Rate:</span> 100%</p>
                        <p><span>Avg. Response Time:</span> &lt;1 Hrs.</p>
                        <p><span>Aircraft:</span> 2</p>
                        <p><span>Address:</span> ${operatorAddress}</p>
                        <p><span>Hours:</span> 24 Hours</p>
                        <p><span>Certificate ID:</span> Ask us</p>
                      </div>
                      <div class="opadet_top_right">
                        <iframe
  src="https://www.google.com/maps/embed/v1/place?key=AIzaSyALUxYUzfuMmECXI_q_it5VBehlUCE_Ml8&q=${encodeURIComponent(
     operatorAddress,
  )}"
  frameborder="0"
  style="border:0;"
  allowfullscreen=""
  loading="lazy">
</iframe>

                      </div>
                    </div>
                    <div class="opadet_bottom">
                      <div class="opadet_bottom_heading">
                        <ul>
                          <li><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754085d1d9a01ce66e3a259_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Icon" /></li>
                          <li>0.00 | 0</li>
                          <li><span>Reviews</span></li>
                        </ul>
                      </div>
                      <div class="opadet_bottom_review">
                        <div class="opadet_bottom_review_left">
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>5 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>4 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>3 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>2 Stars</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                          <div class="reviewitem_block">
                            <div class="obarleft">
                              <p>1 Star</p>
                            </div>
                            <div class="obarmiddle">
                              <span></span>
                            </div>
                            <div class="obaright">
                              <p>(0)</p>
                            </div>
                          </div>
                        </div>
                        <div class="opadet_bottom_review_right">
                          <h3>Rating Breakdown</h3>
                          <div class="opadet_bottom_review_right_item">
                            <p>Seller communication level <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                            <p>Recommended to other passengers <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                            <p>Service as described <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                            <p>Flight cancellation rate <span>0% <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>              
                </div>
              </div>
              <!-- Operators Tab End -->
            </div>            
          <div class="tabxholder"><li class="tiggitem" data-item="tab${index}pl">Policies</li>
            <!-- Policies Tab -->
            <div data-cnt="tab${index}pl" class="item_tab_one">
              <div class="poli_wrapper">
                <h3>Available Fare Classes</h3>  
                <div class="poli_box_wrapper">
                  <!-- Value Fare Class -->
                  <div class="polibox">
                    <div class="polibox_heading">
                      <h3>Value <span>+ $0</span></h3>                              
                    </div>
                    <div class="polibox_cnt">
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>$95 Change Fee:</span> Applies to all flight modifications.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>Non-Refundable:</span> Flight fare is non-refundable for client-initiated cancellations.</p>
                      </div>
                    </div>
                  </div>
                  <!-- Flex Fare Class -->
                  <div class="polibox polibox_two">
                    <div class="polibox_heading">
                      <h3>Flex <span>+ 5%</span></h3>
                      <span class="recom">Recommended</span>                              
                    </div>
                    <div class="polibox_cnt">
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>No Change Fee</span></p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>No Fee:</span> Cancel more than 336 hours (14 days) before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>50% Fee:</span> Cancel 96 – 336 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>Cancellations refunded in Jettly flight credits only</span></p>
                      </div>
                    </div>
                  </div>
                  <!-- Premium Fare Class -->
                  <div class="polibox">
                    <div class="polibox_heading">
                      <h3>Premium <span>+ 10%</span></h3>
                    </div>
                    <div class="polibox_cnt">
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>No Change Fee</span></p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>No Fee:</span> Cancel more than 168 hours (7 days) before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>50% Fee:</span> Cancel 96 – 168 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>Cancellations refunded to original payment method or in Jettly flight credits</span></p>
                      </div>
                    </div>
                  </div>
                </div>  
              </div>
            </div>
            <!-- Policies Tab End -->            
          </div>
          <div class="tabxholder"><li class="tiggitem" data-item="tab${index}py">Payments</li>
            <!-- Payments Tab -->
            <div data-cnt="tab${index}py" class="item_tab_one">
              <div class="payment_tab">
                <h3>Payments</h3>
                <div class="payment_wrapper">
                  <div class="paymenttab_left">
                    <div class="paymenttab_left_item">
                      <div class="paymenttab_item_img">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                      </div>
                      <p>Pay in full upon aircraft availability confirmation by ${
                         item.operator_txt_text
                      }</p>
                    </div>
                    <div class="paymenttab_left_item">
                      <div class="paymenttab_item_img">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                      </div>
                      <p>Acceptable payment methods: Visa, MasterCard, American Express, Wire, ACH, Cryptocurrency</p>
                    </div>
                    <div class="paymenttab_left_item">
                      <div class="paymenttab_item_img">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                      </div>
                      <p>You will receive an invoice for the trip once the aircraft is confirmed</p>
                    </div>
                  </div>
                  <div class="paymenttab_right">
                    <p>Upon Confirmation</p>
                    <div class="paymenttab_right_percent">
                      <div class="paybar"></div>
                      <div class="paybar_text">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        <span>100%</span>
                      </div>
                    </div>
                    <p>Pay in full once the aircraft is confirmed available by ${
                       item.operator_txt_text
                    }.</p>
                    <div class="payment">
                      <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755a86f952bce124bed0a9d_payment.png" alt="Payment Methods" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- Payments Tab End -->
          </div>
          <div class="tabxholder"><li class="tiggitem" data-item="tab${index}ask">Ask Us a Question</li>
            <!-- Ask Us a Question Tab -->
            <div data-cnt="tab${index}ask" class="item_tab_one">
              <div class="payment_tab">
                <h3>Message ${item.operator_txt_text}</h3>
                <div class="payment_wrapper askform">
                  <form>
                    <textarea required placeholder="Type your message here"></textarea>
                    <input type="hidden" value="${
                       item.managed_a_c_operator_custom_managed_air_operator
                    }" />
                    <div class="submitbtn">
                      <button type="submit"><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755b3a876accbd14f83880f_plan.png" alt="Send Message Icon" /></button>
                    </div>
                  </form>
                </div>
              </div>
            </div>
            <!-- Ask Us a Question Tab End -->
          </div>
        </ul>  
        <img class="mbcross" src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6769a03a6c10d465500c1cff_cross.png" alt="" />      
      </div>
      
      </div>
      <div class="tab_item_cnt_wrapper">
        <!-- Images Tab -->
        <div data-cnt="tab${index}img" class="item_tab_one">
          <div class="tab_one_heading">
            <h3>EXTERIOR IMAGES</h3>
          </div>
          <div class="tab_one_slider ${checkExtLength <= 3 ? "sliderOn" : ""}">
            <div class="swiper slide${index}block">
              <div class="swiper-wrapper"> ${allImageExt} </div>
            </div>
            <div class="swipper_ctrl">
              <span class="nav${index}prev">
                <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
              </span>
              <span class="nav${index}next">
                <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
              </span>
            </div>
          </div>
          <div class="tab_one_heading tab_one_next_heading">
            <h3>INTERIOR IMAGES</h3>
          </div>
          <div class="tab_one_slider ${checkIntLength <= 3 ? "sliderOn" : ""}">
            <div class="swiper slide${index}int">
              <div class="swiper-wrapper"> ${allImageInt} </div>
            </div>
            <div class="swipper_ctrl">
              <span class="int${index}prev">
                <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c63ca921fbf5867f7906_blackleft.avif" alt="Previous Slide" />
              </span>
              <span class="int${index}next">
                <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6731c6505bf5a2a3eb0d037b_blackright.avif" alt="Next Slide" />
              </span>
            </div>
          </div>
        </div>

        <!-- Details Tab -->
        <div data-cnt="tab${index}det" class="item_tab_one">
          <div class="detailstb_wrapper">
            <div class="detailstb_left">
              <h3>Details</h3>
              <div class="detailstb_left_det">
                <div class="detailstb_left_det_item">
                  <p>Class:</p>
                  <p>${item.class_text}</p>
                </div>
                <div class="detailstb_left_det_item">
                  <p>Max Passengers:</p>
                  <p>${item.pax_number}</p>
                </div>
                <div class="detailstb_left_det_item">
                  <p>Year of Make:</p>
                  <p>${item.year_of_manufacture_number}</p>
                </div>
                <div class="detailstb_left_det_item">
                  <p>Wyvern Safety Rated:</p>
                  <p>${item.wyvern_rating_text}</p>
                </div>
                <div class="detailstb_left_det_item">
                  <p>ARG/US Safety Rating:</p>
                  <p>${item.argus_us_rating_text}</p>
                </div>
                ${
                   item.insured_amount_number > 0
                      ? `
                      <div class="detailstb_left_det_item">
                        <p>Liability Insurance:</p>
                        <p>$${item.insured_amount_number.toLocaleString()}</p>
                      </div>
                    `
                      : ""
                }
              </div>
            </div>
            <div class="detailstb_left detailstb_right">
              <h3>Amenities</h3>
              <div class="detailstb_left_det">
                ${words}
              </div>
            </div>
          </div>
        </div>

        <!-- Itinerary Tab -->
        <div data-cnt="tab${index}it" class="item_tab_one">
          <div class="inttabDet">
            <h3>Flight Legs</h3>
            ${intabWrapper}
          </div>
        </div>

        <!-- Operators Tab -->
        <div data-cnt="tab${index}op" class="item_tab_one">
          <div class="opadetails">
            <h3>Operator</h3>
            <div class="opadet_wrapper">
              <div class="opadet_top">
                <div class="opadet_top_left">
                  <p>${item.operator_txt_text}</p>
                  <img src="${item.operator_logo_image}" alt="Operator Logo" />
                </div>
                <div class="opadet_top_middle">
                  <p><span>Response Rate:</span> 100%</p>
                  <p><span>Avg. Response Time:</span> &lt;1 Hrs.</p>
                  <p><span>Aircraft:</span> 2</p>
                  <p><span>Address:</span> ${operatorAddress}</p>
                  <p><span>Hours:</span> 24 Hours</p>
                  <p><span>Certificate ID:</span> Ask us</p>
                </div>
                <div class="opadet_top_right">
                  <iframe
  src="https://www.google.com/maps/embed/v1/place?key=AIzaSyALUxYUzfuMmECXI_q_it5VBehlUCE_Ml8&q=${encodeURIComponent(
     operatorAddress,
  )}"
  frameborder="0"
  style="border:0;"
  allowfullscreen=""
  loading="lazy">
</iframe>

                </div>
              </div>
              <div class="opadet_bottom">
                <div class="opadet_bottom_heading">
                  <ul>
                    <li><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754085d1d9a01ce66e3a259_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Icon" /></li>
                    <li>0.00 | 0</li>
                    <li><span>Reviews</span></li>
                  </ul>
                </div>
                <div class="opadet_bottom_review">
                  <div class="opadet_bottom_review_left">
                    <div class="reviewitem_block">
                      <div class="obarleft">
                        <p>5 Stars</p>
                      </div>
                      <div class="obarmiddle">
                        <span></span>
                      </div>
                      <div class="obaright">
                        <p>(0)</p>
                      </div>
                    </div>
                    <div class="reviewitem_block">
                      <div class="obarleft">
                        <p>4 Stars</p>
                      </div>
                      <div class="obarmiddle">
                        <span></span>
                      </div>
                      <div class="obaright">
                        <p>(0)</p>
                      </div>
                    </div>
                    <div class="reviewitem_block">
                      <div class="obarleft">
                        <p>3 Stars</p>
                      </div>
                      <div class="obarmiddle">
                        <span></span>
                      </div>
                      <div class="obaright">
                        <p>(0)</p>
                      </div>
                    </div>
                    <div class="reviewitem_block">
                      <div class="obarleft">
                        <p>2 Stars</p>
                      </div>
                      <div class="obarmiddle">
                        <span></span>
                      </div>
                      <div class="obaright">
                        <p>(0)</p>
                      </div>
                    </div>
                    <div class="reviewitem_block">
                      <div class="obarleft">
                        <p>1 Star</p>
                      </div>
                      <div class="obarmiddle">
                        <span></span>
                      </div>
                      <div class="obaright">
                        <p>(0)</p>
                      </div>
                    </div>
                  </div>
                  <div class="opadet_bottom_review_right">
                    <h3>Rating Breakdown</h3>
                    <div class="opadet_bottom_review_right_item">
                      <p>Seller communication level <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                      <p>Recommended to other passengers <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                      <p>Service as described <span>0.0 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                      <p>Flight cancellation rate <span>0% <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/67540aa6fb2976ffafcecdf2_Jettly-Search-Results-Page-(List-View-Operators-Tab)-Recovered.png" alt="Rating Breakdown Icon" /></span></p>
                    </div>
                  </div>
                </div>
              </div>
            </div>       
          </div>
        </div>
        <!-- Operators Tab End -->     
        <!-- Policies Tab -->
            <div data-cnt="tab${index}pl" class="item_tab_one">
              <div class="poli_wrapper">
                <h3>Available Fare Classes</h3>  
                <div class="poli_box_wrapper">
                  <!-- Value Fare Class -->
                  <div class="polibox">
                    <div class="polibox_heading">
                      <h3>Value <span>+ $0</span></h3>                              
                    </div>
                    <div class="polibox_cnt">
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>$95 Change Fee:</span> Applies to all flight modifications.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>Non-Refundable:</span> Flight fare is non-refundable for client-initiated cancellations.</p>
                      </div>
                    </div>
                  </div>
                  <!-- Flex Fare Class -->
                  <div class="polibox polibox_two">
                    <div class="polibox_heading">
                      <h3>Flex <span>+ 5%</span></h3>
                      <span class="recom">Recommended</span>                              
                    </div>
                    <div class="polibox_cnt">
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>No Change Fee</span></p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>No Fee:</span> Cancel more than 336 hours (14 days) before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>50% Fee:</span> Cancel 96 – 336 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>Cancellations refunded in Jettly flight credits only</span></p>
                      </div>
                    </div>
                  </div>
                  <!-- Premium Fare Class -->
                  <div class="polibox">
                    <div class="polibox_heading">
                      <h3>Premium <span>+ 10%</span></h3>
                    </div>
                    <div class="polibox_cnt">
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>No Change Fee</span></p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>No Fee:</span> Cancel more than 168 hours (7 days) before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>100% Fee:</span> Cancel within 24 hours of departure (no refund).</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>75% Fee:</span> Cancel 24 – 96 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p><span>50% Fee:</span> Cancel 96 – 168 hours before departure.</p>
                      </div>
                      <div class="polibox_cnt_item">
                        <div class="checkicon">
                          <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        </div>
                        <p class="capitalize"><span>Cancellations refunded to original payment method or in Jettly flight credits</span></p>
                      </div>
                    </div>
                  </div>
                </div>  
              </div>
            </div>
            <!-- Policies Tab End -->
            <!-- Payments Tab -->
            <div data-cnt="tab${index}py" class="item_tab_one">
              <div class="payment_tab">
                <h3>Payments</h3>
                <div class="payment_wrapper">
                  <div class="paymenttab_left">
                    <div class="paymenttab_left_item">
                      <div class="paymenttab_item_img">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                      </div>
                      <p>Pay in full upon aircraft availability confirmation by ${
                         item.operator_txt_text
                      }</p>
                    </div>
                    <div class="paymenttab_left_item">
                      <div class="paymenttab_item_img">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                      </div>
                      <p>Acceptable payment methods: Visa, MasterCard, American Express, Wire, ACH, Cryptocurrency</p>
                    </div>
                    <div class="paymenttab_left_item">
                      <div class="paymenttab_item_img">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                      </div>
                      <p>You will receive an invoice for the trip once the aircraft is confirmed</p>
                    </div>
                  </div>
                  <div class="paymenttab_right">
                    <p>Upon Confirmation</p>
                    <div class="paymenttab_right_percent">
                      <div class="paybar"></div>
                      <div class="paybar_text">
                        <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6754150613f571f3ecee0471_check.png" alt="Check Icon" />
                        <span>100%</span>
                      </div>
                    </div>
                    <p>Pay in full once the aircraft is confirmed available by ${
                       item.operator_txt_text
                    }.</p>
                    <div class="payment">
                      <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755a86f952bce124bed0a9d_payment.png" alt="Payment Methods" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- Payments Tab End -->
            <!-- Ask Us a Question Tab -->
            <div data-cnt="tab${index}ask" class="item_tab_one">
              <div class="payment_tab">
                <h3>Message ${item.operator_txt_text}</h3>
                <div class="payment_wrapper askform">
                  <form>
                    <textarea required placeholder="Type your message here"></textarea>
                    <input type="hidden" value="${
                       item.managed_a_c_operator_custom_managed_air_operator
                    }" />
                    <div class="submitbtn">
                      <button type="submit"><img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6755b3a876accbd14f83880f_plan.png" alt="Send Message Icon" /></button>
                    </div>
                  </form>
                </div>
              </div>
            </div>
            <!-- Ask Us a Question Tab End -->
      </div>
    </div>
    `;
}

// Global object to store calculated values by aircraft ID
window.aircraftCalculatedValues = window.aircraftCalculatedValues || {};

// Function to create and append an item block
function createItemBlock(item, index, isHotDeal, fragment, distance, TimeDown) {
   // Determine if pricing should be "On Request" (non-airplane trip classifications)
   const isOnRequest =
      tripClassification !== "" && tripClassification !== "airplane";

   const cruiseSpeed = item.cruise_speed_avg_fixedrate_number || 0;
   const getTotalTime = cruiseSpeed > 0 ? TimeDown / cruiseSpeed : 0;
   const totalHours = Math.floor(getTotalTime);
   const totalMinutes = Math.round((getTotalTime - totalHours) * 60);

   // 2) Calculate final price with possible multipliers
   const multiplier = isHotDeal
      ? 0.8
      : apiData.response.is_international
        ? 1.5
        : 1;

   let calculatedValue;
   if (isOnRequest) {
      calculatedValue = 0;
   } else if (cruiseSpeed === 0 || distance / cruiseSpeed < 1) {
      calculatedValue = Math.round(item.price_per_hour_fixedrate_number);
   } else {
      calculatedValue = Math.round(
         (distance / cruiseSpeed) *
            item.price_per_hour_fixedrate_number *
            multiplier,
      );
   }
   const calculateTotal = isOnRequest
      ? "On Request"
      : calculatedValue.toLocaleString();

   // Store the calculated value globally for tracking
   window.aircraftCalculatedValues[item._id] = calculatedValue;

   const calculateHoursRate = item.price_per_hour_fixedrate_number * multiplier;

   // 3) Count exterior/interior images
   const checkExtLength = Array.isArray(item.exterior_images_list_image)
      ? item.exterior_images_list_image.length
      : 0;
   const checkIntLength = Array.isArray(item.interior_images_list_image)
      ? item.interior_images_list_image.length
      : 0;

   // Generate the HTML for exterior/interior images
   const allImageExt = Array.isArray(item.exterior_images_list_image)
      ? item.exterior_images_list_image
           .map(
              (imageUrl) => `
            <div class="swiper-slide">
              <div class="dyslideItem">
                <img class="individulimages" src="${imageUrl}" alt="Aircraft Exterior Image" />
              </div>
            </div>
          `,
           )
           .join("")
      : "";

   const allImageInt = Array.isArray(item.interior_images_list_image)
      ? item.interior_images_list_image
           .map(
              (imageUrl) => `
            <div class="swiper-slide">
              <div class="dyslideItem">
                <img class="individulimages" src="${imageUrl}" alt="Aircraft Interior Image" />
              </div>
            </div>
          `,
           )
           .join("")
      : "";

   // 4) Amenities
   const amenities = Array.isArray(item.amenities_txt_list_text)
      ? item.amenities_txt_list_text
      : null;

   const words = amenities
      ? amenities
           .map((amen) => {
              const wordsArr = amen.split(" ");
              const firstLetter = wordsArr[0][0];
              const lastFirstLetter = wordsArr[wordsArr.length - 1][0];
              return `
            <div class="detleft_item">
              <span>${firstLetter}${lastFirstLetter}</span>
              <p>${amen}</p>                      
            </div>
          `;
           })
           .join("")
      : `<p class="Notfoundarray">Amenities Not Listed? Contact Us for the Latest Details!</p>`;

   const flightLegs = Array.isArray(apiData.response.flight_legs)
      ? [...apiData.response.flight_legs]
      : [];

   const stopInfo =
      item.range_number > flightLegs[0].total_distance__statute_m__number
         ? "Direct"
         : item.range_number * 2 >
             flightLegs[0].total_distance__statute_m__number
           ? "1 Stop"
           : item.range_number * 2 <
               flightLegs[0].total_distance__statute_m__number
             ? "2 Stop"
             : "";

   const intabWrapper = flightLegs
      .map((leg) => {
         const hoursLeg = Math.floor(getTotalTime);
         const minutesLeg = Math.round((getTotalTime - hoursLeg) * 60);
         const totalSecondsLeg = hoursLeg * 3600 + minutesLeg * 60;

         const dateStart = leg.date_date;
         const dateObjStart = new Date(dateStart); // Correctly parse ISO or date string

         const formattedDateStart = dateObjStart.toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
         });

         const formattedTimeStart = dateObjStart.toLocaleTimeString("en-US", {
            hour: "numeric",
            minute: "2-digit",
            hour12: true,
         });

         // ✅ Add milliseconds to dateObjStart.getTime()
         const finalTimeLeg = new Date(
            dateObjStart.getTime() + totalSecondsLeg * 1000,
         );

         const formattedDateEnd = finalTimeLeg.toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
         });

         const formattedTimeEnd = finalTimeLeg.toLocaleTimeString("en-US", {
            hour: "numeric",
            minute: "2-digit",
            hour12: true,
         });

         const legCruiseSpeed = item.cruise_speed_avg_fixedrate_number || 0;
         const legTime =
            legCruiseSpeed > 0
               ? leg.total_distance__statute_m__number / legCruiseSpeed
               : 0;
         const legTimehours = Math.floor(legTime);
         const legTimeminutes = Math.floor((legTime - legTimehours) * 60);
         const legformattedTime = isOnRequest
            ? "On Request"
            : `${legTimehours} H ${legTimeminutes} M`;

         return `
          <div class="intdet_wrapper">
            <div class="intdet_left">
              <img class="operatorlogo" src="${
                 item.operator_logo_image
              }" alt="Operator Logo" />
            </div>
            <div class="intdet_middle">
              <div class="intdet_middle_date">
                <p class="takeoffdate">${formattedDateStart}</p>
                <p class="landdate"${isOnRequest ? ' style="display: none;"' : ""}> - Lands ${formattedDateEnd}</p>
              </div>
              <div class="inted_middle_time">
                <p>${formattedTimeStart}<span${isOnRequest ? ' style="display: none;"' : ""}> - ${formattedTimeEnd}</span></p>
              </div>
              <div class="airportformatname">
                <p>
                  ${leg.mobile_app_from_airport_name_short_text}
                  (${
                     leg.mobile_app_from_airport_iata_code_text
                        ? leg.mobile_app_from_airport_iata_code_text
                        : leg.mobile_app_from_airport_icao_code_text
                          ? leg.mobile_app_from_airport_icao_code_text
                          : leg.mobile_app_from_airport_faa_code_text || "N/A"
                  })
                  -
                  ${leg.mobile_app_to_airport_name_short_text}
                  (${
                     leg.mobile_app_to_airport_iata_code_text
                        ? leg.mobile_app_to_airport_iata_code_text
                        : leg.mobile_app_to_airport_icao_code_text
                          ? leg.mobile_app_to_airport_icao_code_text
                          : leg.mobile_app_to_airport_faa_code_text || "N/A"
                  })
                </p>
              </div>
              <div class="operator_textlist">
                <p>${item.operator_txt_text} • ${item.class_text} • ${
                   item.description_text
                }</p>
              </div>   
              ${
                 isHotDeal
                    ? `<div class="fuelstop hot-deal-fuel-stop" style="display: none;" data-item-id="${item._id}">
                      <p>
                        <img 
                          src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6753e62479df68bd6de939cd_Jettly-Search-Results-Page-(List-View-Itinerary-Tab).png" 
                          alt="Fuel Stop Icon" /> 
                        Possible fuel stop enroute - 
                        <span>+20 mins</span>
                      </p>
                    </div>`
                    : item.range_number > leg.total_distance__statute_m__number
                      ? ""
                      : item.range_number * 2 >
                          leg.total_distance__statute_m__number
                        ? `<div class="fuelstop">
                        <p>
                          <img 
                            src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6753e62479df68bd6de939cd_Jettly-Search-Results-Page-(List-View-Itinerary-Tab).png" 
                            alt="Fuel Stop Icon" /> 
                          Possible fuel stop enroute - 
                          <span>+20 mins</span>
                        </p>
                      </div>`
                        : `<div class="fuelstop">
                      <p>
                        <img 
                          src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6753e62479df68bd6de939cd_Jettly-Search-Results-Page-(List-View-Itinerary-Tab).png" 
                          alt="Fuel Stop Icon" /> 
                        Possible fuel stop enroute - 
                        <span>+20 mins</span>
                      </p>
                    </div>`
              }
            </div>
            <div class="indetright_wrapper"${isOnRequest ? ' style="display: none;"' : ""}>
              <div class="indet_right">
                <img 
                  src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6753e928907492da22caf7fe_flighticon.png" 
                  alt="Flight Time Icon" />
                <span>Flight Time</span>
                <p>${legformattedTime}</p>
              </div>
            </div>
          </div>
        `;
      })
      .join("");

   // 7) Create a wrapper DIV for this entire item
   const itemWrapper = document.createElement("div");
   itemWrapper.className = isHotDeal
      ? "item_block_wrapper hotwrapper"
      : "item_block_wrapper";

   const uniqueId = item._id || `item-${globalIndex}`;
   const isChecked = checkedItems[uniqueId] || false;
   globalIndex++;

   if (isHotDeal) {
      itemWrapper.innerHTML = getHotDealHtml(
         item,
         index,
         calculateTotal,
         totalHours,
         totalMinutes,
         stopInfo,
         allImageExt,
         allImageInt,
         checkExtLength,
         checkIntLength,
         words,
         apiData,
         intabWrapper,
         calculateHoursRate,
         uniqueId,
         isChecked,
      );
   } else {
      itemWrapper.innerHTML = getRegularItemHtml(
         item,
         index,
         calculateTotal,
         totalHours,
         totalMinutes,
         stopInfo,
         allImageExt,
         allImageInt,
         checkExtLength,
         checkIntLength,
         words,
         apiData,
         intabWrapper,
         calculateHoursRate,
         uniqueId,
         isChecked,
         isOnRequest,
      );
   }

   // 9) Finally, append this completed item to your fragment
   fragment.appendChild(itemWrapper);
}

// Debounced filter function
const debouncedFilterData = debounce(() => {
   filterData();
}, 300);

// Function to filter data based on selected filters
function filterData() {
   let filteredSets = [...filteredByRangeSlider];

   filteredSets = filteredSets.filter((item) => {
      const price = item.price_per_hour_fixedrate_number;
      return price >= currentMinPrice && price <= currentMaxPrice;
   });

   if (selectedClasses.length > 0) {
      filteredSets = filteredSets.filter((item) =>
         selectedClasses.includes(item.class_text),
      );
   }

   if (selectedDescriptions.length > 0) {
      filteredSets = filteredSets.filter((item) =>
         selectedDescriptions.includes(item.description_text),
      );
   }

   if (selectedOperators.length > 0) {
      filteredSets = filteredSets.filter((item) =>
         selectedOperators.includes(item.operator_txt_text),
      );
   }

   if (selectedArgusFilters.length > 0) {
      filteredSets = applyArgusFilters(filteredSets, selectedArgusFilters);
   }

   if (selectedIsBaoFilters.length > 0) {
      filteredSets = applyIsBaoFilters(filteredSets, selectedIsBaoFilters);
   }

   if (selectedWyvernFilters.length > 0) {
      filteredSets = applyWyvernFilters(filteredSets, selectedWyvernFilters);
   }

   if (selectedanimalFilters.length > 0) {
      filteredSets = applyAnimalFilters(filteredSets, selectedanimalFilters);
   }

   if (selectedOthersFilters.length > 0) {
      filteredSets = applyOthersFilters(filteredSets, selectedOthersFilters);
   }

   if (departureReadyCheckbox.checked) {
      filteredSets = filteredSets.filter(
         (item) => item.departure_ready__boolean === true,
      );
   }

   if (highTimeCrewCheckbox.checked) {
      filteredSets = filteredSets.filter(
         (item) => item.high_time_crew__boolean === true,
      );
   }

   if (fuelFilters.length > 0) {
      filteredSets = applyFuelFilters(filteredSets, fuelFilters);
   }

   if (filteredSets.length === 0) {
      mainWrapper.innerHTML = `<p class="no-results">No results found for the selected filters.</p>`;
      pagination.innerHTML = "";
      finalResultParagraph.textContent = `0`;
      // updateCheckboxCounts(filteredSets);
      return;
   }

   finalResultParagraph.textContent = ` ${filteredSets.length} `;
   currentPage = 1;
   // updateCheckboxCounts(filteredSets);
   renderPage(currentPage, filteredSets);
   renderPagination(filteredSets);
}

// Function to handle search input
const handleSearchInput = () => {
   const searchTerm = searchInputBox.value.toLowerCase().trim();
   filteredByRangeSlider = aircraftSets.filter(
      (item) =>
         item.description_text &&
         item.description_text.toLowerCase().includes(searchTerm),
   );
   debouncedFilterData();
};

// Attach event listener to search input
searchInputBox.addEventListener("input", handleSearchInput);

// Function to generate generic checkboxes
function generateCheckboxes(wrapper, items, key, labelFormatter, targetArray) {
   wrapper.innerHTML = "";
   const fragment = document.createDocumentFragment();

   const counts = items.reduce((acc, item) => {
      const keyValue = item[key];
      acc[keyValue] = (acc[keyValue] || 0) + 1;
      return acc;
   }, {});

   Object.entries(counts).forEach(([value, count]) => {
      const checkboxWrapper = document.createElement("div");
      checkboxWrapper.classList.add("checkbox_item");
      checkboxWrapper.innerHTML = `
        <label>
          <input type="checkbox" value="${value}" />
          ${labelFormatter(value)} <span>(${count})</span>
        </label>
      `;
      fragment.appendChild(checkboxWrapper);
   });

   wrapper.appendChild(fragment);
   const checkboxes = wrapper.querySelectorAll("input[type='checkbox']");
   checkboxes.forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
         const value = checkbox.value;
         if (checkbox.checked) {
            targetArray.push(value);
         } else {
            const idx = targetArray.indexOf(value);
            if (idx > -1) targetArray.splice(idx, 1);
         }
         debouncedFilterData();
         updateSelectedFilterCount();
      });
   });
}

// Function to generate Argus checkboxes
function generateArgusCheckboxes() {
   const argusData = {
      "Not Rated": "argus_not_rated__boolean",
      Gold: "argus_gold__boolean",
      "Gold +": "argus_gold____boolean",
      Platinum: "argus_platinum__boolean",
   };

   argusCheckboxWrapper.innerHTML = "";
   const fragment = document.createDocumentFragment();

   Object.keys(argusData).forEach((filter) => {
      const count = aircraftSets.filter(
         (item) => item[argusData[filter]] === true,
      ).length;
      const checkboxWrapper = document.createElement("div");
      checkboxWrapper.classList.add("checkbox_item");
      checkboxWrapper.innerHTML = `
        <label>
          <input type="checkbox" value="${filter}" />
          ${filter} <span>(${count})</span>
        </label>
      `;
      fragment.appendChild(checkboxWrapper);
   });

   argusCheckboxWrapper.appendChild(fragment);

   argusCheckboxWrapper
      .querySelectorAll("input[type='checkbox']")
      .forEach((checkbox) => {
         checkbox.addEventListener("change", () => {
            const value = checkbox.value;
            if (checkbox.checked) {
               selectedArgusFilters.push(value);
            } else {
               selectedArgusFilters = selectedArgusFilters.filter(
                  (f) => f !== value,
               );
            }
            debouncedFilterData();
            updateSelectedFilterCount();
         });
      });
}

// Function to generate IsBao checkboxes
function generateIsBaoCheckboxes() {
   const isBaoData = {
      "Not Rated": "is_bao_not_rated__boolean",
      Registered: "is_bao_registered__boolean",
   };

   isBaoCheckboxWrapper.innerHTML = "";
   const fragment = document.createDocumentFragment();

   Object.keys(isBaoData).forEach((filter) => {
      const count = aircraftSets.filter(
         (item) => item[isBaoData[filter]] === true,
      ).length;
      const checkboxWrapper = document.createElement("div");
      checkboxWrapper.classList.add("checkbox_item");
      checkboxWrapper.innerHTML = `
        <label>
          <input type="checkbox" value="${filter}" />
          ${filter} <span>(${count})</span>
        </label>
      `;
      fragment.appendChild(checkboxWrapper);
   });

   isBaoCheckboxWrapper.appendChild(fragment);
   isBaoCheckboxWrapper
      .querySelectorAll("input[type='checkbox']")
      .forEach((checkbox) => {
         checkbox.addEventListener("change", () => {
            const value = checkbox.value;
            if (checkbox.checked) {
               selectedIsBaoFilters.push(value);
            } else {
               selectedIsBaoFilters = selectedIsBaoFilters.filter(
                  (f) => f !== value,
               );
            }
            debouncedFilterData();
            updateSelectedFilterCount();
         });
      });
}

// Function to generate Wyvern checkboxes
function generateWyvernCheckboxes() {
   const wyvernData = {
      "Not Rated": "wyvern_not_rated__boolean",
      "Wyvern Registered": "wyvern_registered__boolean",
      "Wyvern Wingman": "wyvern_wingman__boolean",
   };

   wyvernCheckboxWrapper.innerHTML = "";
   const fragment = document.createDocumentFragment();

   Object.keys(wyvernData).forEach((filter) => {
      const count = aircraftSets.filter(
         (item) => item[wyvernData[filter]] === true,
      ).length;
      const checkboxWrapper = document.createElement("div");
      checkboxWrapper.classList.add("checkbox_item");
      checkboxWrapper.innerHTML = `
        <label>
          <input type="checkbox" value="${filter}" />
          ${filter} <span>(${count})</span>
        </label>
      `;
      fragment.appendChild(checkboxWrapper);
   });

   wyvernCheckboxWrapper.appendChild(fragment);

   wyvernCheckboxWrapper
      .querySelectorAll("input[type='checkbox']")
      .forEach((checkbox) => {
         checkbox.addEventListener("change", () => {
            const value = checkbox.value;
            if (checkbox.checked) {
               selectedWyvernFilters.push(value);
            } else {
               selectedWyvernFilters = selectedWyvernFilters.filter(
                  (f) => f !== value,
               );
            }
            debouncedFilterData();
            updateSelectedFilterCount();
         });
      });
}

// Function to generate Animal checkboxes
function generateAnimalCheckboxes() {
   const animalData = [
      { name: "Enclosed Lavatory", key: "enclosed_lavatory__boolean" },
      { name: "Pets Allowed", key: "pet_friendly__boolean" },
      { name: "Smoking Allowed", key: "smoking_allowed__boolean" },
      { name: "Wi-Fi (Ground based)", key: "wi_fi_ground_based__boolean" },
      {
         name: "Wi-Fi (Satellite based)",
         key: "wi_fi_satellite_based__boolean",
      },
   ];

   animalCheckboxWrapper.innerHTML = "";
   const fragment = document.createDocumentFragment();

   animalData.forEach((item) => {
      const count = aircraftSets.filter((i) => i[item.key] === true).length;
      const checkboxWrapper = document.createElement("div");
      checkboxWrapper.classList.add("checkbox_item");
      checkboxWrapper.innerHTML = `
        <label>
          <input type="checkbox" value="${item.name}" />
          ${item.name} <span>(${count})</span>
        </label>
      `;
      fragment.appendChild(checkboxWrapper);
   });

   animalCheckboxWrapper.appendChild(fragment);

   animalCheckboxWrapper
      .querySelectorAll("input[type='checkbox']")
      .forEach((checkbox) => {
         checkbox.addEventListener("change", () => {
            const value = checkbox.value;
            if (checkbox.checked) {
               selectedanimalFilters.push(value);
            } else {
               selectedanimalFilters = selectedanimalFilters.filter(
                  (f) => f !== value,
               );
            }
            debouncedFilterData();
            updateSelectedFilterCount();
         });
      });
}

// Function to generate Others checkboxes
function generateOthersCheckboxes() {
   const othersData = [
      { name: "Exclude owner approval", key: "oa_required__boolean" },
      { name: "Cargo", key: "cargo_capable__boolean" },
      { name: "Ambulance", key: "ambulance_capable__boolean" },
      { name: "Exclude transient", key: "transient_aircraft__boolean" },
      { name: "Exclude at homebase", key: "at_home_base__boolean" },
   ];

   othersCheckboxWrapper.innerHTML = "";
   const fragment = document.createDocumentFragment();

   othersData.forEach((item) => {
      const count = aircraftSets.filter((i) => i[item.key] === true).length;
      const checkboxWrapper = document.createElement("div");
      checkboxWrapper.classList.add("checkbox_item");
      checkboxWrapper.innerHTML = `
        <label>
          <input type="checkbox" value="${item.name}" />
          ${item.name} <span>(${count})</span>
        </label>
      `;
      fragment.appendChild(checkboxWrapper);
   });

   othersCheckboxWrapper.appendChild(fragment);

   othersCheckboxWrapper
      .querySelectorAll("input[type='checkbox']")
      .forEach((checkbox) => {
         checkbox.addEventListener("change", () => {
            const value = checkbox.value;
            if (checkbox.checked) {
               selectedOthersFilters.push(value);
            } else {
               selectedOthersFilters = selectedOthersFilters.filter(
                  (f) => f !== value,
               );
            }
            debouncedFilterData();
            updateSelectedFilterCount();
         });
      });
}

// Function to generate Fuel Stop checkboxes
function generateFuelCheckboxes() {
   const fuelCount = {
      Direct: 0,
      "1 Stop": 0,
      "2 Stop": 0,
      "": 0,
   };

   aircraftSets.forEach((item) => {
      if (item.range_number > longestFlight) {
         fuelCount["Direct"]++;
      } else if (item.range_number * 2 > longestFlight) {
         fuelCount["1 Stop"]++;
      } else if (item.range_number * 2 < longestFlight) {
         fuelCount["2 Stop"]++;
      } else {
         fuelCount[""]++;
      }
   });

   fuelCheckboxWrapper.innerHTML = "";
   const fragment = document.createDocumentFragment();

   Object.entries(fuelCount).forEach(([filter, count]) => {
      const checkboxWrapper = document.createElement("div");
      checkboxWrapper.classList.add("checkbox_item");
      checkboxWrapper.innerHTML = `
        <label>
          <input type="checkbox" value="${filter}" />
          ${filter} <span>(${count})</span>
        </label>
      `;
      fragment.appendChild(checkboxWrapper);
   });

   fuelCheckboxWrapper.appendChild(fragment);

   fuelCheckboxWrapper
      .querySelectorAll("input[type='checkbox']")
      .forEach((checkbox) => {
         checkbox.addEventListener("change", () => {
            const value = checkbox.value;
            if (checkbox.checked) {
               fuelFilters.push(value);
            } else {
               fuelFilters = fuelFilters.filter((f) => f !== value);
            }
            debouncedFilterData();
            updateSelectedFilterCount();
         });
      });
}

// Function to generate all checkboxes
function generateAllCheckboxes() {
   generateCheckboxes(
      categoryCheckboxWrapper,
      aircraftSets,
      "class_text",
      (value) => value,
      selectedClasses,
   );
   generateCheckboxes(
      descriptionCheckboxWrapper,
      aircraftSets,
      "description_text",
      (value) => value,
      selectedDescriptions,
   );
   generateCheckboxes(
      sellerCheckboxWrapper,
      aircraftSets,
      "operator_txt_text",
      (value) => value,
      selectedOperators,
   );
   generateArgusCheckboxes();
   generateIsBaoCheckboxes();
   generateWyvernCheckboxes();
   generateAnimalCheckboxes();
   generateOthersCheckboxes();
   generateFuelCheckboxes();
}

// Function to filter data and render UI
function filterAndRender() {
   filterData();
}

// Function to initialize simple sliders
function initializeSimpleSliders() {
   // Select all slider containers
   const sliders = document.querySelectorAll(".slider-container");

   sliders.forEach((slider) => {
      const slides = slider.querySelectorAll(".slide");
      const nextBtn = slider.querySelector(".next-btn");
      const prevBtn = slider.querySelector(".prev-btn");
      let currentSlide = 0;

      // Function to show a specific slide
      function showSlide(index) {
         slides.forEach((slide, idx) => {
            slide.classList.toggle("active", idx === index);
         });
      }

      // Show the first slide initially
      showSlide(currentSlide);

      // Event listener for Next button
      nextBtn.addEventListener("click", () => {
         currentSlide = (currentSlide + 1) % slides.length;
         showSlide(currentSlide);
      });

      // Event listener for Prev button
      prevBtn.addEventListener("click", () => {
         currentSlide = (currentSlide - 1 + slides.length) % slides.length;
         showSlide(currentSlide);
      });
   });
}

// Function to create and set up the modal
function createModal() {
   // Create modal elements
   const modal = document.createElement("div");
   modal.id = "imageModal";
   modal.classList.add("modal");
   modal.innerHTML = `
      <span class="close">&times;</span>
      <button class="modal-prev">&#10094;</button>
      <img class="modal-content" src="" alt="Expanded Image">
      <button class="modal-next">&#10095;</button>
    `;
   document.body.appendChild(modal);

   // Reference modal elements
   const imageModal = document.getElementById("imageModal");
   const modalImg = imageModal.querySelector(".modal-content");
   const closeBtn = imageModal.querySelector(".close");
   const prevBtn = imageModal.querySelector(".modal-prev");
   const nextBtn = imageModal.querySelector(".modal-next");

   let currentImages = [];
   let currentIndex = 0;

   // Function to open the modal
   function openModal(images, index) {
      currentImages = images;
      currentIndex = index;
      modalImg.src = currentImages[currentIndex];
      imageModal.style.display = "flex";
   }

   // Function to close the modal
   function closeModal() {
      imageModal.style.display = "none";
      modalImg.src = "";
   }

   // Function to show the previous image
   function showPrevImage() {
      if (currentImages.length === 0) return;
      currentIndex =
         (currentIndex - 1 + currentImages.length) % currentImages.length;
      modalImg.src = currentImages[currentIndex];
   }

   // Function to show the next image
   function showNextImage() {
      if (currentImages.length === 0) return;
      currentIndex = (currentIndex + 1) % currentImages.length;
      modalImg.src = currentImages[currentIndex];
   }

   // Event listeners
   closeBtn.addEventListener("click", closeModal);
   prevBtn.addEventListener("click", showPrevImage);
   nextBtn.addEventListener("click", showNextImage);

   // Close modal when clicking outside the image
   window.addEventListener("click", function (event) {
      if (event.target === imageModal) {
         closeModal();
      }
   });

   // Make the modal accessible via keyboard
   document.addEventListener("keydown", function (event) {
      if (imageModal.style.display === "block") {
         if (event.key === "ArrowLeft") {
            showPrevImage();
         } else if (event.key === "ArrowRight") {
            showNextImage();
         } else if (event.key === "Escape") {
            closeModal();
         }
      }
   });

   // Expose the openModal function to be accessible outside
   window.openModal = openModal;
}

// Function to attach image click listeners for modal functionality
function attachImageClickListeners() {
   document.querySelectorAll(".dyslideItem img").forEach((img) => {
      img.addEventListener("click", function () {
         // Attempt to find the closest slider container
         const sliderContainer = img.closest(".slider-container");

         if (sliderContainer) {
            // If a slider container exists, gather all images within it
            const images = Array.from(
               sliderContainer.querySelectorAll(".dyslideItem img"),
            ).map((i) => i.src);

            // Determine the index of the clicked image within the slider
            const index = Array.from(
               sliderContainer.querySelectorAll(".dyslideItem img"),
            ).indexOf(img);

            // Open the modal with the list of images and the current index
            window.openModal(images, index);
         } else {
            // If no slider container, display only the clicked image in the modal
            window.openModal([img.src], 0);
         }
      });
   });
}

// Function to initialize Swiper sliders (already defined above)
// (Included within renderPage and createItemBlock functions)

// Function to initialize Swiper sliders
// Re-defining to ensure it's included
function initializeSwipers() {
   const slideBlocks = document.querySelectorAll(
      "[class*='slide'][class*='block'], [class*='slide'][class*='int']",
   );
   const uniqueIndexes = new Set();
   slideBlocks.forEach((block) => {
      const classes = block.className.split(" ");
      classes.forEach((cl) => {
         const matchBlock = cl.match(/slide(\d+)block/);
         const matchInt = cl.match(/slide(\d+)int/);
         if (matchBlock) {
            uniqueIndexes.add(matchBlock[1]);
         }
         if (matchInt) {
            uniqueIndexes.add(matchInt[1]);
         }
      });
   });

   uniqueIndexes.forEach((sliderClass) => {
      new Swiper(`.slide${sliderClass}block`, {
         slidesPerView: 3,
         loop: true,
         navigation: {
            nextEl: `.nav${sliderClass}next`,
            prevEl: `.nav${sliderClass}prev`,
         },
         spaceBetween: 10,
      });

      new Swiper(`.slide${sliderClass}int`, {
         slidesPerView: 3,
         loop: true,
         navigation: {
            nextEl: `.int${sliderClass}next`,
            prevEl: `.int${sliderClass}prev`,
         },
         spaceBetween: 10,
      });
   });
}

function initialize() {
   const apiUrlOneWay =
      "https://operators-dashboard.bubbleapps.io/api/1.1/wf/webflow_one_way_flight";
   const apiUrlRoundTrip =
      "https://operators-dashboard.bubbleapps.io/api/1.1/wf/webflow_round_trip_flight";
   const apiUrlMultiCity =
      "https://operators-dashboard.bubbleapps.io/api/1.1/wf/webflow_submitmultileg";
   const storedData = sessionStorage.getItem("storeData");
   let way;

   if (storedData) {
      const findWay = JSON.parse(storedData);
      way = findWay.way;
   }

   let data = {};
   let apiUrl = "";

   if (way === "one way") {
      const sessionData = JSON.parse(storedData);
      data = {
         "from airport id": sessionData.fromId,
         "to airport id": sessionData.toId,
         date_as_text: sessionData.dateAsText,
         time_as_text: sessionData.timeAsText,
         App_Out_Date_As_Text: sessionData.appDate,
         pax: sessionData.pax,
         date: sessionData.timeStamp,
         "leg_1_departure_include_nearby?": sessionData.isFromNearby,
         "leg_1_arrival_include_nearby?": sessionData.isToNearby,
         trip_classification: sessionData.trip_classification,
      };
      apiUrl = apiUrlOneWay;
   } else if (way === "round trip") {
      const sessionData = JSON.parse(storedData);
      data = {
         "out-dep airport id": sessionData.fromId,
         "out-arr airport id": sessionData.toId,
         "ret-dep airport id": sessionData.returnFromId,
         "ret-arr airport id": sessionData.returnToId,
         "out-dep date": sessionData.timeStamp,
         "ret-date": sessionData.timeStampReturn,
         "out-pax": sessionData.pax,
         "ret-pax": sessionData.paxReturn,
         Dep_date_as_text: sessionData.dateAsText,
         Ret_date_as_text: sessionData.returnDateAsText,
         Dep_time_as_text: sessionData.timeAsText,
         Ret_time_as_text: sessionData.timeAsTextReturn,
         App_Out_Date_As_Text: sessionData.appDate,
         App_Ret_Date_As_Text: sessionData.appDateReturn,
         "leg_1_departure_include_nearby?": sessionData.isFromNearby,
         "leg_1_arrival_include_nearby?": sessionData.isToNearby,
         "leg_2_departure_include_nearby?": sessionData.isToNearby,
         "leg_2_arrival_include_nearby?": sessionData.isFromNearby,
         trip_classification: sessionData.trip_classification,
      };
      apiUrl = apiUrlRoundTrip;
   } else if (way === "multi-city") {
      const sessionData = JSON.parse(storedData);
      data = {
         "from airport id": sessionData.fromId,
         "to airport id": sessionData.toId,
         "to airport id": sessionData.toId,
         date: sessionData.timeStamp,
         pax: sessionData.pax,
         date_as_text: sessionData.dateAsText,
         time_as_text: sessionData.timeAsText,
         App_Out_Date_As_Text: sessionData.appDate,
         trip_classification: sessionData.trip_classification,
      };
      apiUrl = apiUrlMultiCity;
   } else {
      console.error("Invalid 'way' value in sessionStorage.");
      hideLoader();
      return;
   }

   fetch(apiUrl, {
      method: "POST",
      headers: {
         "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
   })
      .then((response) => response.json())
      .then((responseData) => {
         console.log("✅ Main API Response:", responseData);
         apiData = responseData;
         longestFlight = apiData.response.longest_flight_leg;
         flightRequestId = apiData.response.flightrequest;

         tripClassification = (
            apiData.response.trip_classification || ""
         ).toLowerCase();

         // Save flightRequestId in sessionStorage as an array
         let storedFlightIds = JSON.parse(
            sessionStorage.getItem("flightRequestId") || "[]",
         );
         if (flightRequestId && !storedFlightIds.includes(flightRequestId)) {
            storedFlightIds.push(flightRequestId);
            sessionStorage.setItem(
               "flightRequestId",
               JSON.stringify(storedFlightIds),
            );

            // Check if user is logged in and send the data
            const userEmail = Cookies.get("userEmail");
            const authToken = Cookies.get("authToken");
            if (userEmail && authToken) {
               sendFlightRequestIdsIfLoggedIn();
            }
         }

         if (apiData.response) {
            for (const key in apiData.response) {
               if (key.startsWith("aircraft_set_")) {
                  aircraftSets.push(...apiData.response[key]);
               }
            }
         }

         finalResultParagraph.textContent = ` ${aircraftSets.length} `;
         updateCheckboxCounts(aircraftSets);
         hideLoader();

         // hourly rage filter range slider
         const minPriceHourRate = Math.min(
            ...aircraftSets.map((item) => item.price_per_hour_fixedrate_number),
         );
         const maxPriceHourRate = Math.max(
            ...aircraftSets.map((item) => item.price_per_hour_fixedrate_number),
         );
         currentMinPrice = minPriceHourRate;
         currentMaxPrice = maxPriceHourRate;

         // Grab the needed DOM elements (IDs must match the HTML you created above)
         const priceSlider = document.getElementById("priceSlider");
         const priceTrack = priceSlider.querySelector(".slider-track");
         const priceRange = priceSlider.querySelector(".slider-range");
         const priceThumbLeft = document.getElementById("priceThumbLeft");
         const priceThumbRight = document.getElementById("priceThumbRight");
         const priceMinValueInput = document.querySelector("span#min");
         const priceMaxValueInput = document.querySelector("span#max");

         // Initialize numeric inputs to the initial min/max
         priceMinValueInput.textContent =
            Math.round(currentMinPrice).toLocaleString();
         priceMaxValueInput.textContent =
            Math.round(currentMaxPrice).toLocaleString();

         // Utility: convert "price" to % along the slider track
         function priceToPercent(price) {
            const range = maxPriceHourRate - minPriceHourRate;
            if (range === 0) return 0;
            return ((price - minPriceHourRate) / range) * 100;
         }

         // Utility: convert % back to a "price" (rounded)
         function percentToPrice(percent) {
            return Math.round(
               (percent / 100) * (maxPriceHourRate - minPriceHourRate) +
                  minPriceHourRate,
            );
         }

         // Update the thumb positions + the fill
         function updatePriceSliderPositions() {
            const leftPercent = priceToPercent(currentMinPrice);
            const rightPercent = priceToPercent(currentMaxPrice);

            // Move the thumbs
            priceThumbLeft.style.left = `${leftPercent}%`;
            priceThumbRight.style.left = `${rightPercent}%`;

            // Fill between them
            priceRange.style.left = `${leftPercent}%`;
            priceRange.style.width = `${rightPercent - leftPercent}%`;
         }

         // Make sure left doesn't cross right, etc.
         function clampPrice(value, isLeftThumb) {
            if (isLeftThumb) {
               // If moving left thumb, don't let it exceed currentMaxPrice
               return Math.min(value, currentMaxPrice);
            } else {
               // If moving right thumb, don't let it go below currentMinPrice
               return Math.max(value, currentMinPrice);
            }
         }

         // Initialize positions once
         updatePriceSliderPositions();

         // Variables to track if we're dragging
         let draggingPriceLeft = false;
         let draggingPriceRight = false;

         // Mouse/touch handlers
         function onPointerDownLeft() {
            draggingPriceLeft = true;
         }
         function onPointerDownRight() {
            draggingPriceRight = true;
         }
         function onPointerUp() {
            draggingPriceLeft = false;
            draggingPriceRight = false;
         }
         function onPointerMove(e) {
            if (!draggingPriceLeft && !draggingPriceRight) return;

            const rect = priceSlider.getBoundingClientRect();
            const sliderX = rect.left;
            const sliderWidth = rect.width;

            // pointer X (mouse or touch)
            let px = e.clientX || (e.touches && e.touches[0].clientX);
            let relativeX = px - sliderX;
            let percent = (relativeX / sliderWidth) * 100;

            // Bound in [0..100]
            if (percent < 0) percent = 0;
            if (percent > 100) percent = 100;

            const newPrice = percentToPrice(percent);

            if (draggingPriceLeft) {
               currentMinPrice = clampPrice(newPrice, true);
               priceMinValueInput.textContent =
                  currentMinPrice.toLocaleString();
            }
            if (draggingPriceRight) {
               currentMaxPrice = clampPrice(newPrice, false);
               priceMaxValueInput.textContent =
                  currentMaxPrice.toLocaleString();
            }

            updatePriceSliderPositions();
            debouncedFilterData(); // We'll call your existing debounced filter
         }

         // Attach events
         priceThumbLeft.addEventListener("mousedown", onPointerDownLeft);
         priceThumbRight.addEventListener("mousedown", onPointerDownRight);

         priceThumbLeft.addEventListener("touchstart", onPointerDownLeft, {
            passive: true,
         });
         priceThumbRight.addEventListener("touchstart", onPointerDownRight, {
            passive: true,
         });

         window.addEventListener("mousemove", onPointerMove);
         window.addEventListener("touchmove", onPointerMove, {
            passive: false,
         });
         window.addEventListener("mouseup", onPointerUp);
         window.addEventListener("touchend", onPointerUp);

         filteredByRangeSlider = [...aircraftSets];

         minYear = Math.min(
            ...aircraftSets.map((item) => item.year_of_manufacture_number),
         );
         maxYear = new Date().getFullYear();

         minYearExt = Math.min(
            ...aircraftSets
               .map((item) => item.exterior_refurbished_year_number)
               .filter(
                  (year) =>
                     typeof year === "number" && !isNaN(year) && year > 0,
               ),
         );

         minYearInt = Math.min(
            ...aircraftSets
               .map((item) => item.refurbished_year_number)
               .filter(
                  (year) =>
                     typeof year === "number" && !isNaN(year) && year > 0,
               ),
         );

         minYearIns = Math.min(
            ...aircraftSets
               .map((item) => item.insured_amount_number)
               .filter(
                  (amount) => typeof amount === "number" && !isNaN(amount),
               ),
         );

         maxYearIns = Math.max(
            ...aircraftSets
               .map((item) => item.insured_amount_number)
               .filter(
                  (amount) => typeof amount === "number" && !isNaN(amount),
               ),
         );

         // Initialize Range Slider for Year of Manufacture
         rangeSlider.min = minYear;
         rangeSlider.max = maxYear;
         rangeSlider.value = minYear;
         rangeValueDisplay.textContent = `Newer than: ${minYear}`;

         rangeSlider.addEventListener("input", (e) => {
            const selectedYear = parseInt(e.target.value, 10);
            rangeValueDisplay.textContent = `Newer than: ${selectedYear}`;
            filteredByRangeSlider = aircraftSets.filter(
               (item) => item.year_of_manufacture_number >= selectedYear,
            );
            debouncedFilterData();
         });

         // Initialize Exterior Refurbished Year Slider
         extSlider.min = minYearExt;
         extSlider.max = maxYear;
         extSlider.value = minYearExt;
         if (minYearExt > 0) {
            extValueDisplay.textContent = `Greater than: ${minYearExt}`;
         } else {
            extValueDisplay.textContent = "";
         }

         extSlider.addEventListener("input", (e) => {
            const selectedYear = parseInt(e.target.value, 10);
            if (selectedYear > 0) {
               extValueDisplay.textContent = `Greater than: ${selectedYear}`;
            } else {
               extValueDisplay.textContent = "";
            }
            filteredByRangeSlider = aircraftSets.filter(
               (item) => item.exterior_refurbished_year_number >= selectedYear,
            );
            debouncedFilterData();
         });

         // Initialize Interior Refurbished Year Slider
         intSlider.min = minYearInt;
         intSlider.max = maxYear;
         intSlider.value = minYearInt;
         if (minYearInt > 0) {
            intValueDisplay.textContent = `Greater than: ${minYearInt}`;
         } else {
            intValueDisplay.textContent = "";
         }

         intSlider.addEventListener("input", (e) => {
            const selectedYear = parseInt(e.target.value, 10);
            if (selectedYear > 0) {
               intValueDisplay.textContent = `Greater than: ${selectedYear}`;
            } else {
               intValueDisplay.textContent = "";
            }
            filteredByRangeSlider = aircraftSets.filter(
               (item) => item.refurbished_year_number >= selectedYear,
            );
            debouncedFilterData();
         });

         // Initialize Insured Amount Slider
         insSlider.min = minYearIns;
         insSlider.max = maxYearIns;
         insSlider.step = 250000;
         insSlider.value = minYearIns;
         if (minYearIns > 0) {
            insValueDisplay.textContent = `Greater than: $${minYearIns.toLocaleString()}`;
         } else {
            insValueDisplay.textContent = "";
         }

         insSlider.addEventListener("input", (e) => {
            const selectedAmount = parseInt(e.target.value, 10);
            if (selectedAmount > 0) {
               insValueDisplay.textContent = `Greater than: $${selectedAmount.toLocaleString()}`;
            } else {
               insValueDisplay.textContent = "";
            }
            filteredByRangeSlider = aircraftSets.filter(
               (item) => item.insured_amount_number >= selectedAmount,
            );
            debouncedFilterData();
         });

         // Event listeners for Departure Ready and High Time Crew Checkboxes
         departureReadyCheckbox.addEventListener("change", () => {
            debouncedFilterData();
            updateSelectedFilterCount();
         });

         highTimeCrewCheckbox.addEventListener("change", () => {
            debouncedFilterData();
            updateSelectedFilterCount();
         });

         // Generate all checkboxes based on the data
         generateAllCheckboxes();

         // Initialize Modal
         createModal();

         // Hide filter sliders affected by missing cruise speed / pricing data
         const isOnRequestGlobal =
            tripClassification !== "" && tripClassification !== "airplane";
         if (isOnRequestGlobal) {
            const sliderIds = [
               "priceSlider",
               "range",
               "extslider",
               "insslider",
            ];
            sliderIds.forEach((id) => {
               const el = document.getElementById(id);
               if (el) {
                  const section = el.closest(".mkyear");
                  if (section) section.style.display = "none";
               }
            });
         }

         // Initial render of the first page
         filterAndRender();
      })
      .catch((error) => {
         console.error("Error:", error);
         hideLoader();
      });
}

// !══════════════════════════════════════════════════════════════
// !           Trip Details Collector popup code Start
// !══════════════════════════════════════════════════════════════

function initQuotePopup(details) {
   // ── Helpers ─────────────────────────────────────────────────

   function time12to24(timeStr) {
      if (!timeStr) return "00:00:00";
      const match = timeStr.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
      if (!match) return "00:00:00";
      let h = parseInt(match[1], 10);
      const m = match[2];
      const ampm = match[3].toUpperCase();
      if (ampm === "AM" && h === 12) h = 0;
      if (ampm === "PM" && h !== 12) h += 12;
      return `${String(h).padStart(2, "0")}:${m}:00`;
   }

   function generateTimeSlots() {
      const slots = [];
      for (let h = 0; h < 24; h++) {
         for (let m = 0; m < 60; m += 30) {
            const hour12 = h % 12 === 0 ? 12 : h % 12;
            const ampm = h < 12 ? "AM" : "PM";
            slots.push(
               `${String(hour12).padStart(2, "0")}:${m === 0 ? "00" : "30"} ${ampm}`,
            );
         }
      }
      return slots;
   }

   function formatDateDisplay(dateStr) {
      if (!dateStr) return "Select Date";
      const [year, month, day] = dateStr.split("-");
      const date = new Date(year, month - 1, day);
      return date.toLocaleDateString("en-US", {
         day: "numeric",
         month: "short",
         year: "numeric",
      });
   }

   // ── Determine trip type ─────────────────────────────────────

   const wayLower = (details.way || "").toLowerCase();
   const isOneWay = wayLower.includes("one");
   const isMultiCity = wayLower.includes("multi");
   const isRoundTrip = !isOneWay && !isMultiCity;

   // ── Build HTML ──────────────────────────────────────────────

   const container = document.querySelector(".dt_popup_flight_form");
   if (!container) return;

   const formattedDate = details.dateAsText || "";
   const formattedReturnDate = details.returnDateAsText || "";

   function buildLegHTML(legIndex, badgeText, dateValue) {
      const displayDate = formatDateDisplay(dateValue);
      return `
         <div class="dtp_leg_block" data-leg-index="${legIndex}">
            <div class="dtp_leg_badge">${badgeText}</div>
            <div class="dtp_leg_fields">
               <div class="dtp_date_field">
                  <label>DEPARTURE DATE</label>
                  <div class="dtp_date_input_wrapper">
                     <input type="text" class="store-date-input" data-leg-index="${legIndex}" data-date-value="${dateValue}" value="${displayDate}" readonly placeholder="Select Date" />
                     <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6a5dcef85210fea67e54f59a_date.svg" alt="calendar" class="dtp_date_icon" />
                     <div class="dtp_calendar_dropdown" style="display:none;">
                        <div class="calendar-wrapper">
                           <div class="month-nav">
                              <button type="button" class="cal_prev">
                                 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6a5cb7fb70221493ca0848e4_Group%203.svg" alt="prev" />
                              </button>
                              <h3 class="cal_month_year"></h3>
                              <button type="button" class="cal_next">
                                 <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6a5cb7fbe1af4cb77dfe4a01_Group%202.svg" alt="next" />
                              </button>
                           </div>
                           <div class="days-header">
                              <span>SUN</span><span>MON</span><span>TUE</span><span>WED</span>
                              <span>THU</span><span>FRI</span><span>SAT</span>
                           </div>
                           <ul class="days-grid"></ul>
                        </div>
                     </div>
                  </div>
               </div>
               <div class="dtp_time_field">
                   <label>PREFERRED DEPARTURE TIME</label>
                   <div class="dtp_time_input_wrapper">
                      <input type="text" class="departure-time-input" data-leg-index="${legIndex}" readonly placeholder="Select time" value="" />
                      <img src="https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6a5dcef819824fd8eee58abe_clock.svg" alt="clock" class="dtp_time_icon" />
                      <div class="time-dropdown" style="display:none;"></div>
                   </div>
               </div>
            </div>
         </div>
      `;
   }

   let tripHTML = "";

   if (isOneWay) {
      tripHTML = buildLegHTML(
         0,
         `Leg 1: ${details.fromShortName || ""} → ${details.toShortName || ""}`,
         formattedDate,
      );
   } else if (isRoundTrip) {
      tripHTML =
         buildLegHTML(
            0,
            `Leg 1: ${details.fromShortName || ""} → ${details.toShortName || ""}`,
            formattedDate,
         ) +
         buildLegHTML(
            1,
            `Leg 2: ${details.toShortName || ""} → ${details.fromShortName || ""}`,
            formattedReturnDate,
         );
   } else if (isMultiCity) {
      const dates = Array.isArray(details.dateAsText)
         ? details.dateAsText
         : [details.dateAsText];
      const fromNames = Array.isArray(details.fromShortName)
         ? details.fromShortName
         : [details.fromShortName];
      const toNames = Array.isArray(details.toShortName)
         ? details.toShortName
         : [details.toShortName];

      for (let i = 0; i < dates.length; i++) {
         tripHTML += buildLegHTML(
            i,
            `Leg ${i + 1}: ${fromNames[i] || ""} → ${toNames[i] || ""}`,
            dates[i] || "",
         );
      }
   }

   container.innerHTML = tripHTML;

   // ── Popup toast helper ──────────────────────────────────────

   function showDtToast(message) {
      const dtToastMessage = document.getElementById("dtToastMessage");
      const dtToastEl = document.getElementById("dtToast");
      if (dtToastMessage && dtToastEl) {
         dtToastMessage.textContent = message;
         dtToastEl.style.display = "block";
         setTimeout(function () {
            dtToastEl.style.display = "none";
         }, 4000);
      }
   }

   // ── Show the popup ──────────────────────────────────────────

   const wrapper = document.querySelector(".dt_wrapper");
   const firstPopup = wrapper
      ? wrapper.querySelector(".dt_popup:not(.dt_popup_final)")
      : null;
   const secondPopup = wrapper
      ? wrapper.querySelector(".dt_popup_final")
      : null;

   if (wrapper) {
      // Initially show only 1st popup
      if (firstPopup) firstPopup.style.display = "block";
      if (secondPopup) secondPopup.style.display = "none";

      // Set dynamic category name
      const dyname = wrapper.querySelector(".dyname");
      if (dyname) dyname.textContent = tripClassification;

      wrapper.style.display = "flex";
      wrapper.style.opacity = "1";
      wrapper.style.transform = "scale(1)";
      document.body.style.overflow = "hidden";
   }

   // ── Close / Cancel handlers ─────────────────────────────────

   const closeBtns = document.querySelectorAll("#dt_popup_close");
   const cancelBtn = document.getElementById("dt_cancel_btn");
   const finalCancelBtn = document.getElementById("final_cancel_dth");
   const submitBtn = document.getElementById("dt_submit_btn");

   function closeAllPopups() {
      if (wrapper) {
         wrapper.style.display = "none";
         document.body.style.overflow = "";
      }
   }

   closeBtns.forEach((btn) => btn.addEventListener("click", closeAllPopups));
   if (cancelBtn) cancelBtn.addEventListener("click", closeAllPopups);
   if (finalCancelBtn) finalCancelBtn.addEventListener("click", closeAllPopups);
   if (submitBtn) {
      submitBtn.addEventListener("click", async () => {
         // ── Validate date and time inputs ──────────────────────

         const dateInputs = container.querySelectorAll(".store-date-input");
         const timeInputs = container.querySelectorAll(".departure-time-input");
         let allFilled = true;

         dateInputs.forEach((input) => {
            if (!input.value) {
               allFilled = false;
               input.style.border = "1.5px solid red";
            } else {
               input.style.border = "";
            }
         });

         timeInputs.forEach((input) => {
            if (!input.value) {
               allFilled = false;
               input.style.border = "1.5px solid red";
            } else {
               input.style.border = "";
            }
         });

         if (!allFilled) {
            showDtToast("Please select date and time before proceeding.");
            return;
         }

         // ── Read date/time directly from popup inputs ──────────

         function dateTimeToUnix(dateStr, timeStr) {
            const [y, mo, d] = dateStr.split("-").map(Number);
            const [h, mi, s] = (timeStr || "00:00:00").split(":").map(Number);
            return Date.UTC(y, mo - 1, d, h, mi, s);
         }

         function dateTimeToText(dateStr, timeStr) {
            const [y, mo, d] = dateStr.split("-").map(Number);
            const [h, mi] = (timeStr || "00:00:00").split(":").map(Number);
            const date = new Date(y, mo - 1, d, h, mi);
            return date.toLocaleString("en-US", {
               month: "short",
               day: "numeric",
               year: "numeric",
               hour: "numeric",
               minute: "2-digit",
               hour12: true,
            });
         }

         const allDateInputs = container.querySelectorAll(".store-date-input");
         const allTimeInputs = container.querySelectorAll(
            ".departure-time-input",
         );

         let dateAsTextArray = [];
         let dateTimestampArray = [];

         allDateInputs.forEach((dateInput, i) => {
            const dateVal = dateInput.getAttribute("data-date-value");
            const timeVal = time12to24(allTimeInputs[i]?.value || "");
            dateAsTextArray.push(dateTimeToText(dateVal, timeVal));
            dateTimestampArray.push(dateTimeToUnix(dateVal, timeVal));
         });

         // ── Send API request ───────────────────────────────────

         const authToken = Cookies.get("authToken");
         const reqFlightId = flightRequestId || "";

         // Disable button while loading
         const originalText = submitBtn.textContent;
         submitBtn.textContent = "Please Wait...";
         submitBtn.style.pointerEvents = "none";
         submitBtn.style.opacity = "0.6";

         try {
            const response = await fetch(
               "https://operators-dashboard.bubbleapps.io/api/1.1/wf/custom_quote_request",
               {
                  method: "POST",
                  headers: {
                     "Content-Type": "application/json",
                     Authorization: `Bearer ${authToken}`,
                  },
                  body: JSON.stringify({
                     date_as_text: dateAsTextArray,
                     date: dateTimestampArray,
                     flightrequestid: reqFlightId,
                  }),
               },
            );

            const result = await response.json();

            // Success → show 2nd popup (confirmation)
            if (firstPopup) firstPopup.style.display = "none";
            if (secondPopup) secondPopup.style.display = "block";
         } catch (error) {
            console.error("Quote request error:", error);
            showDtToast("Something went wrong. Please try again.");
         } finally {
            // Restore button state
            submitBtn.textContent = originalText;
            submitBtn.style.pointerEvents = "";
            submitBtn.style.opacity = "";
         }
      });
   }

   // ── Setup custom date pickers ───────────────────────────────

   const months = [
      "January",
      "February",
      "March",
      "April",
      "May",
      "June",
      "July",
      "August",
      "September",
      "October",
      "November",
      "December",
   ];

   container.querySelectorAll(".store-date-input").forEach((input) => {
      const dropdown = input
         .closest(".dtp_date_input_wrapper")
         .querySelector(".dtp_calendar_dropdown");
      const daysGrid = dropdown.querySelector(".days-grid");
      const monthYearText = dropdown.querySelector(".cal_month_year");
      const prevBtn = dropdown.querySelector(".cal_prev");
      const nextBtn = dropdown.querySelector(".cal_next");

      const initialDate = input.getAttribute("data-date-value");
      let currYear, currMonth;
      let selectedDate = null;

      if (initialDate) {
         const p = initialDate.split("-");
         currYear = parseInt(p[0], 10);
         currMonth = parseInt(p[1], 10) - 1;
         selectedDate = {
            day: parseInt(p[2], 10),
            month: currMonth,
            year: currYear,
         };
      } else {
         const now = new Date();
         currYear = now.getFullYear();
         currMonth = now.getMonth();
      }

      const isSameDate = (d1, d2) =>
         d1 &&
         d2 &&
         d1.day === d2.day &&
         d1.month === d2.month &&
         d1.year === d2.year;

      function renderCalendar() {
         const firstDayofMonth = new Date(currYear, currMonth, 1).getDay();
         const lastDateofMonth = new Date(currYear, currMonth + 1, 0).getDate();
         const lastDayofLastMonth = new Date(currYear, currMonth, 0).getDate();
         const lastDayofMonth = new Date(
            currYear,
            currMonth,
            lastDateofMonth,
         ).getDay();

         const now = new Date();
         const today = new Date(
            now.getFullYear(),
            now.getMonth(),
            now.getDate(),
         );

         let liTag = "";

         const prevMonthVal = currMonth === 0 ? 11 : currMonth - 1;
         const prevMonthYear = currMonth === 0 ? currYear - 1 : currYear;

         for (let i = firstDayofMonth; i > 0; i--) {
            const day = lastDayofLastMonth - i + 1;
            const dateToCheck = new Date(prevMonthYear, prevMonthVal, day);
            let className = "prev-month-day";

            if (dateToCheck < today) {
               className += " disabled";
            } else {
               const currentDayObj = {
                  day,
                  month: prevMonthVal,
                  year: prevMonthYear,
               };
               if (isSameDate(currentDayObj, selectedDate)) {
                  className += " active";
               }
            }
            liTag += `<li class="${className}" data-day="${day}" data-month="${prevMonthVal}" data-year="${prevMonthYear}">${day}</li>`;
         }

         for (let i = 1; i <= lastDateofMonth; i++) {
            const dateToCheck = new Date(currYear, currMonth, i);
            let className = "";

            if (dateToCheck < today) {
               className = "disabled";
            } else {
               const currentDayObj = {
                  day: i,
                  month: currMonth,
                  year: currYear,
               };
               if (isSameDate(currentDayObj, selectedDate)) {
                  className = "active";
               }
            }
            liTag += `<li class="${className}" data-day="${i}" data-month="${currMonth}" data-year="${currYear}">${i}</li>`;
         }

         const nextMonthVal = currMonth === 11 ? 0 : currMonth + 1;
         const nextMonthYear = currMonth === 11 ? currYear + 1 : currYear;

         for (let i = lastDayofMonth; i < 6; i++) {
            const day = i - lastDayofMonth + 1;
            liTag += `<li class="prev-month-day" data-day="${day}" data-month="${nextMonthVal}" data-year="${nextMonthYear}">${day}</li>`;
         }

         monthYearText.textContent = `${months[currMonth].toUpperCase()}, ${currYear}`;
         daysGrid.innerHTML = liTag;

         daysGrid.querySelectorAll("li:not(.disabled)").forEach((li) => {
            li.addEventListener("click", (e) => {
               e.stopPropagation();
               const d = parseInt(li.getAttribute("data-day"));
               const m = parseInt(li.getAttribute("data-month"));
               const y = parseInt(li.getAttribute("data-year"));

               selectedDate = { day: d, month: m, year: y };

               const dateStr = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
               input.value = formatDateDisplay(dateStr);
               input.setAttribute("data-date-value", dateStr);
               dropdown.style.display = "none";
            });
         });
      }

      prevBtn.addEventListener("click", (e) => {
         e.stopPropagation();
         currMonth--;
         if (currMonth < 0) {
            currMonth = 11;
            currYear--;
         }
         renderCalendar();
      });

      nextBtn.addEventListener("click", (e) => {
         e.stopPropagation();
         currMonth++;
         if (currMonth > 11) {
            currMonth = 0;
            currYear++;
         }
         renderCalendar();
      });

      const dateIcon = input
         .closest(".dtp_date_input_wrapper")
         .querySelector(".dtp_date_icon");
      const openCalendar = (e) => {
         e.stopPropagation();
         // Close all other dropdowns
         container.querySelectorAll(".dtp_calendar_dropdown").forEach((dd) => {
            if (dd !== dropdown) dd.style.display = "none";
         });
         container.querySelectorAll(".time-dropdown").forEach((dd) => {
            dd.style.display = "none";
         });
         renderCalendar();
         dropdown.style.display = "block";
      };
      input.addEventListener("click", openCalendar);
      dateIcon.addEventListener("click", openCalendar);

      document.addEventListener("click", (e) => {
         if (
            !dropdown.contains(e.target) &&
            e.target !== input &&
            e.target !== dateIcon
         ) {
            dropdown.style.display = "none";
         }
      });
   });

   // ── Setup time dropdowns ────────────────────────────────────

   const timeInputs = container.querySelectorAll(".departure-time-input");
   const timeDropdowns = container.querySelectorAll(".time-dropdown");
   const slots = generateTimeSlots();

   timeInputs.forEach((input, idx) => {
      const dropdown = timeDropdowns[idx];
      if (!dropdown) return;

      dropdown.innerHTML =
         `<div class="time-reset">RESET</div>` +
         slots.map((time) => `<div class="time-slot">${time}</div>`).join("");

      const timeIcon = input
         .closest(".dtp_time_input_wrapper")
         .querySelector(".dtp_time_icon");
      const openTimeDropdown = (e) => {
         e.stopPropagation();
         // Close all other dropdowns
         container.querySelectorAll(".time-dropdown").forEach((dd) => {
            if (dd !== dropdown) dd.style.display = "none";
         });
         container.querySelectorAll(".dtp_calendar_dropdown").forEach((dd) => {
            dd.style.display = "none";
         });
         dropdown.style.display = "block";
      };
      input.addEventListener("click", openTimeDropdown);
      timeIcon.addEventListener("click", openTimeDropdown);

      document.addEventListener("click", (e) => {
         if (
            !dropdown.contains(e.target) &&
            e.target !== input &&
            e.target !== timeIcon
         ) {
            dropdown.style.display = "none";
         }
      });

      dropdown.addEventListener("click", (e) => {
         if (e.target.classList.contains("time-slot")) {
            input.value = e.target.textContent;
            dropdown.style.display = "none";
         }
         if (e.target.classList.contains("time-reset")) {
            input.value = "";
            dropdown.style.display = "none";
         }
      });
   });
}

document.addEventListener("DOMContentLoaded", function () {
   initialize();

   // Listen for custom login/logout events and re-render page
   window.addEventListener("userLoggedIn", function () {
      handleLoginStatusChange();
   });

   window.addEventListener("userLoggedOut", function () {
      handleLoginStatusChange();
   });

   // Monitor cookie changes via a polling mechanism
   let lastLoginState = isUserLoggedIn();
   setInterval(function () {
      const currentLoginState = isUserLoggedIn();
      if (currentLoginState !== lastLoginState) {
         lastLoginState = currentLoginState;
         handleLoginStatusChange();
      }
   }, 1000); // Check every second
});
