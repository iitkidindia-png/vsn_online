
function startScanner() {
    const html5QrCode = new Html5Qrcode("video");

    html5QrCode.start(
        { facingMode: "environment" },
        {
            fps: 10,
            qrbox: 250
        },
        onScanSuccess
    );
}

function onScanSuccess(decodedText) {
    // Fill barcode input
    document.getElementById("barcode").value = decodedText;

     // Auto match dropdown
    let bookSelect = document.getElementById("bookSelect");
    for (let i = 0; i < bookSelect.options.length; i++) {
        if (bookSelect.options[i].value === decodedText) {
            bookSelect.selectedIndex = i;
            $('#bookSelect').trigger('change'); // for select2
            break;
        }
    }
    // OPTIONAL: auto-submit (uncomment if needed)
    // document.querySelector("form[action='/add_to_cart']").submit();
}