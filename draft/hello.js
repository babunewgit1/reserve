const airQouteLink = document.querySelectorAll(".air_link");
const popup = document.getElementById("search_bar_pop-up");
if (airQouteLink && popup) {
   airQouteLink.forEach((airQoutebtn) => {
      airQoutebtn.addEventListener("click", function (e) {
         e.preventDefault();
         popup.style.display = "block";
      });
   });
}
