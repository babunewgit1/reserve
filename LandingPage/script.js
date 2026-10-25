const searchBar = document.querySelector(".search-bar");
const fields = [...searchBar.querySelectorAll(".search-field")];

const airportIndex = algoliasearch(
   "ZSPO7HB4MN",
   "2a3621a18dca4f1fb757e9ddaea72440",
).initIndex("Airports");

const openField = (field) => {
   fields.forEach((item) => item !== field && closeField(item));
   field.classList.add("is-open");
   field.querySelector("[aria-expanded]").setAttribute("aria-expanded", "true");
};

const closeField = (field) => {
   field.classList.remove("is-open");
   field
      .querySelector("[aria-expanded]")
      .setAttribute("aria-expanded", "false");
};

const clamp = (index, length) => Math.min(Math.max(index, 0), length - 1);

/* City / airport search */
const cityField = searchBar.querySelector(".search-field--city");
const cityInput = cityField.querySelector("#city");
const airportInput = cityField.querySelector("[name='airport']");
const cityHint = cityField.querySelector(".search-dropdown__hint");
const cityResults = cityField.querySelector(".search-dropdown__results");
const hintText = cityHint.textContent;
let activeResult = -1;

const setActiveResult = (index) => {
   activeResult = index;
   [...cityResults.children].forEach((item, i) =>
      item.classList.toggle("is-active", i === index),
   );
   cityResults.children[index]?.scrollIntoView({ block: "nearest" });
};

const airportIcon =
   "https://cdn.prod.website-files.com/6713759f858863c516dbaa19/6739f54808efbe5ead7a23c1_Screenshot_1-removebg-preview.avif";

const chooseAirport = (name) => {
   cityInput.value = name;
   airportInput.value = name;
   [...cityResults.children].forEach((item) =>
      item.classList.toggle("is-selected", item.dataset.name === name),
   );
   closeField(cityField);
};

const renderResults = (names = [], message = hintText) => {
   cityResults.replaceChildren(
      ...names.map((name) => {
         const item = document.createElement("li");
         const icon = document.createElement("img");
         const text = document.createElement("span");
         item.className = "search-result";
         item.classList.toggle("is-selected", name === airportInput.value);
         item.setAttribute("role", "option");
         item.dataset.name = name;
         icon.className = "search-result__icon";
         icon.src = airportIcon;
         icon.alt = "";
         text.className = "search-result__name";
         text.textContent = name;
         item.append(icon, text);
         item.addEventListener("click", () => chooseAirport(name));
         return item;
      }),
   );

   activeResult = -1;
   cityResults.hidden = !names.length;
   cityHint.hidden = names.length > 0;
   cityHint.textContent = message;
};

let searchTimer;
let latestQuery = "";

const searchAirports = () => {
   const query = cityInput.value.trim();
   latestQuery = query;
   clearTimeout(searchTimer);

   if (!query) {
      renderResults();
      return;
   }

   searchTimer = setTimeout(() => {
      airportIndex
         .search(query)
         .then(({ hits }) => {
            if (query !== latestQuery) return;
            const names = hits.map((hit) => hit["All Fields"]).filter(Boolean);
            renderResults(names, "No results found.");
         })
         .catch((error) => {
            console.error("Algolia search error:", error);
            if (query === latestQuery)
               renderResults([], "Error fetching results.");
         });
   }, 300);
};

cityInput.addEventListener("focus", () => openField(cityField));

cityField
   .querySelector(".search-field__control")
   .addEventListener("click", () => {
      cityInput.focus();
      openField(cityField);
   });

cityInput.addEventListener("input", () => {
   airportInput.value = "";
   cityField.classList.remove("has-error");
   openField(cityField);
   searchAirports();
});

cityInput.addEventListener("keydown", (event) => {
   const items = cityResults.children;

   if ((event.key === "ArrowDown" || event.key === "ArrowUp") && items.length) {
      event.preventDefault();
      setActiveResult(
         clamp(
            activeResult + (event.key === "ArrowDown" ? 1 : -1),
            items.length,
         ),
      );
   }

   if (event.key === "Enter" && activeResult > -1) {
      event.preventDefault();
      items[activeResult].click();
   }
});

/* Select dropdowns */
searchBar.querySelectorAll(".search-field--select").forEach((field) => {
   const toggle = field.querySelector(".search-field__control");
   const value = field.querySelector(".search-field__value");
   const input = field.querySelector("input[type='hidden']");
   const options = [...field.querySelectorAll(".search-option")];

   const choose = (option) => {
      options.forEach((item) => {
         item.classList.toggle("is-selected", item === option);
         item.setAttribute("aria-selected", item === option);
      });
      value.textContent = option.textContent;
      input.value = option.dataset.value;
      field.classList.add("has-value");
      closeField(field);
      toggle.focus();
   };

   toggle.addEventListener("click", () => {
      if (field.classList.contains("is-open")) closeField(field);
      else openField(field);
   });

   toggle.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      openField(field);
      (
         options.find((option) => option.classList.contains("is-selected")) ??
         options[0]
      ).focus();
   });

   options.forEach((option, index) => {
      option.addEventListener("click", () => choose(option));
      option.addEventListener("keydown", (event) => {
         if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            options[
               clamp(
                  index + (event.key === "ArrowDown" ? 1 : -1),
                  options.length,
               )
            ].focus();
         }

         if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            choose(option);
         }
      });
   });
});

/* Close on outside click, focus leaving the field, or Escape */
fields.forEach((field) => {
   field
      .querySelector(".search-dropdown")
      .addEventListener("mousedown", (event) => event.preventDefault());
   field.addEventListener("focusout", (event) => {
      if (!field.contains(event.relatedTarget)) closeField(field);
   });
});

document.addEventListener("click", (event) => {
   fields.forEach(
      (field) => !field.contains(event.target) && closeField(field),
   );
});

document.addEventListener("keydown", (event) => {
   const field = fields.find((item) => item.classList.contains("is-open"));
   if (event.key !== "Escape" || !field) return;
   closeField(field);
   field.querySelector("[aria-expanded]").focus();
});

/* Search reserve opportunities */
const apiUrl =
   "https://jettly.com/version-test/api/1.1/wf/search_reserve_opportunities";
const submitButton = searchBar.querySelector(".search-bar__submit");
const flexibilityDays = { "24-hours": 1, "2-3-days": 3, "1-week": 7 };

// MM/DD/YYYY
const formatDate = (date) =>
   [date.getMonth() + 1, date.getDate()]
      .map((part) => String(part).padStart(2, "0"))
      .concat(date.getFullYear())
      .join("/");

const getToDate = (fromDate, flexibility) => {
   const toDate = new Date(fromDate);
   if (flexibility in flexibilityDays)
      toDate.setDate(toDate.getDate() + flexibilityDays[flexibility]);
   else toDate.setFullYear(toDate.getFullYear() + 1);
   return toDate;
};

searchBar.addEventListener("submit", (event) => {
   event.preventDefault();

   const address = cityInput.value.trim();
   if (!address) {
      cityField.classList.add("has-error");
      cityInput.focus();
      return;
   }

   const { distance, flexibility } = Object.fromEntries(
      new FormData(searchBar),
   );
   const fromDate = new Date();
   const params = new URLSearchParams({
      from_date: formatDate(fromDate),
      to_date: formatDate(getToDate(fromDate, flexibility)),
      address,
      items_until: 50,
      items_from: 1,
      radius_miles: distance && distance !== "not-sure" ? distance : 1000,
   });

   submitButton.disabled = true;
   fetch(`${apiUrl}?${params}`)
      .then((response) => {
         if (!response.ok) throw new Error(`HTTP ${response.status}`);
         return response.json();
      })
      .then((data) => console.log("Reserve opportunities:", data))
      .catch((error) => console.error("Reserve search error:", error))
      .finally(() => (submitButton.disabled = false));
});
