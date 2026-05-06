// ============================================================
// scan.js — Image upload, OCR scan, email confirmation
// ============================================================

var uploadArea       = document.getElementById("uploadArea")
var uploadInner      = document.getElementById("uploadInner")
var imageInput       = document.getElementById("imageInput")
var imagePreview     = document.getElementById("imagePreview")
var previewImg       = document.getElementById("previewImg")
var removeImageBtn   = document.getElementById("removeImage")
var categorySelect   = document.getElementById("category")
var idCardHint       = document.getElementById("idCardHint")
var scanBox          = document.getElementById("scanBox")
var scanStatus       = document.getElementById("scanStatus")
var scanSpinner      = document.getElementById("scanSpinner")
var scanText         = document.getElementById("scanText")
var scanResult       = document.getElementById("scanResult")
var resultRoll       = document.getElementById("resultRoll")
var resultName       = document.getElementById("resultName")
var resultEmail      = document.getElementById("resultEmail")
var emailConfirmBox  = document.getElementById("emailConfirmBox")
var btnSendYes       = document.getElementById("btnSendYes")
var btnSendNo        = document.getElementById("btnSendNo")
var emailChoiceMsg   = document.getElementById("emailChoiceMsg")
var scanNote         = document.getElementById("scanNote")
var locationInput    = document.getElementById("location")
var fileSizeError    = document.getElementById("fileSizeError")

// Hidden form inputs
var uploadedFilename  = document.getElementById("uploadedFilename")
var scannedRoll       = document.getElementById("scannedRoll")
var scannedEmail      = document.getElementById("scannedEmail")
var scannedName       = document.getElementById("scannedName")
var sendEmailChoice   = document.getElementById("sendEmailChoice")

var selectedFile = null
var isIdCard     = false
var MAX_IMAGE_BYTES = 2 * 1024 * 1024
var FILE_SIZE_ERROR_TEXT = "File size should not be greater than 2 mb."

function showPopupMessage(text, type) {
    var wrap = document.querySelector(".flash-wrap")
    if (!wrap) {
        wrap = document.createElement("div")
        wrap.className = "flash-wrap"
        document.body.appendChild(wrap)
    }
    var flash = document.createElement("div")
    flash.className = "flash flash-" + (type || "error")
    flash.textContent = text
    var closeBtn = document.createElement("button")
    closeBtn.className = "flash-x"
    closeBtn.textContent = "×"
    closeBtn.addEventListener("click", function () {
        flash.remove()
    })
    flash.appendChild(closeBtn)
    wrap.appendChild(flash)
    setTimeout(function () {
        if (flash && flash.parentNode) {
            flash.remove()
        }
    }, 4500)
}

function showFileSizeError() {
    if (!fileSizeError) return
    fileSizeError.textContent = FILE_SIZE_ERROR_TEXT
    fileSizeError.style.display = "block"
    fileSizeError.style.visibility = "visible"
    showPopupMessage(FILE_SIZE_ERROR_TEXT, "error")
}

function hideFileSizeError() {
    if (!fileSizeError) return
    fileSizeError.style.display = "none"
}


// ---- Category change: show/hide ID card hint ----
categorySelect.addEventListener("change", function () {
    isIdCard = categorySelect.value === "ID Card"
    idCardHint.style.display = isIdCard ? "block" : "none"

    // If image already uploaded and category just changed to ID Card, scan now
    if (isIdCard && selectedFile && !uploadedFilename.value) {
        uploadAndScan(selectedFile)
    }
})


// ---- Click upload area ----
uploadArea.addEventListener("click", function (e) {
    if (e.target === removeImageBtn) return
    imageInput.click()
})


// ---- Drag and drop ----
uploadArea.addEventListener("dragover", function (e) {
    e.preventDefault()
    uploadArea.classList.add("drag-over")
})

uploadArea.addEventListener("dragleave", function () {
    uploadArea.classList.remove("drag-over")
})

uploadArea.addEventListener("drop", function (e) {
    e.preventDefault()
    uploadArea.classList.remove("drag-over")
    var files = e.dataTransfer.files
    if (files.length > 0) {
        handleFileSelected(files[0])
    }
})


// ---- File picked ----
imageInput.addEventListener("change", function () {
    if (imageInput.files.length > 0) {
        handleFileSelected(imageInput.files[0])
    }
})


// ---- Remove image ----
removeImageBtn.addEventListener("click", function () {
    clearImage()
})


// ---- Handle file selection ----
function handleFileSelected(file) {
    hideFileSizeError()
    if (!file.type.startsWith("image/")) {
        showPopupMessage("Please select an image file.", "error")
        return
    }

    if (file.size > MAX_IMAGE_BYTES) {
        showFileSizeError()
        clearImage()
        return
    }
    selectedFile = file

    // Show preview
    var reader = new FileReader()
    reader.onload = function (e) {
        previewImg.src = e.target.result
        imagePreview.style.display = "flex"
        uploadInner.style.display = "none"
    }
    reader.readAsDataURL(file)

    uploadAndScan(file)
}


// ---- Upload + scan via AJAX ----
function uploadAndScan(file) {
    hideFileSizeError()
    isIdCard = categorySelect.value === "ID Card"

    var formData = new FormData()
    formData.append("image", file)

    // If ID card: show spinner while scanning
    if (isIdCard) {
        scanBox.style.display = "block"
        scanResult.style.display = "none"
        emailConfirmBox.style.display = "none"
        emailChoiceMsg.style.display = "none"
        scanStatus.style.display = "flex"
        scanText.textContent = "Scanning ID card for roll number..."
    }

    fetch("/scan-id-card", {
        method: "POST",
        body:   formData
    })
    .then(function (response) { return response.json() })
    .then(function (data) {

        // Always save filename
        if (data.filename) {
            uploadedFilename.value = data.filename
        }

        if (!isIdCard) {
            // Not an ID card — just saved the image
            if (!data.success && data.message) {
                showPopupMessage(data.message, "error")
            }
            return
        }

        // Hide spinner, show result
        scanStatus.style.display = "none"
        scanResult.style.display = "block"

        if (data.success) {
            // Roll number detected
            scannedRoll.value  = data.roll  || ""
            scannedEmail.value = data.email || ""
            scannedName.value  = data.name  || ""

            resultRoll.textContent  = data.roll  || "—"
            resultName.textContent  = data.name  || "—"
            resultEmail.textContent = data.email || "—"

            scanNote.textContent = ""
            scanBox.classList.add("scan-box-success")
            scanBox.classList.remove("scan-box-error")

            // Show the email confirmation question
            emailConfirmBox.style.display = "block"
            emailChoiceMsg.style.display  = "none"
            // Reset choice
            sendEmailChoice.value = ""

        } else {
            // No roll number found
            scannedRoll.value  = ""
            scannedEmail.value = ""
            scannedName.value  = ""

            resultRoll.textContent  = "Not detected"
            resultName.textContent  = "—"
            resultEmail.textContent = "—"

            emailConfirmBox.style.display = "none"

            scanNote.textContent = "⚠️ " + (data.message || "Could not read roll number. You can still submit.")
            scanNote.style.color = "var(--accent)"
            scanBox.classList.add("scan-box-error")
            scanBox.classList.remove("scan-box-success")
        }
    })
    .catch(function (err) {
        console.error("Scan error:", err)
        if (isIdCard) {
            scanStatus.style.display = "none"
            scanResult.style.display = "block"
            scanNote.textContent = "⚠️ Scan failed. You can still submit the report."
        }
    })
}


// ---- YES — mark choice (email will be sent on form submit) ----
btnSendYes.addEventListener("click", function () {
    var email    = scannedEmail.value
    var name     = scannedName.value || "Student"
    var location = locationInput.value.trim() || "Campus"

    if (!email || email === "unknown") {
        emailChoiceMsg.textContent = "⚠️ No valid email to send to."
        emailChoiceMsg.style.color = "var(--accent)"
        emailChoiceMsg.style.display = "block"
        return
    }

    // Mark choice so the backend sends after full form submission
    sendEmailChoice.value = "yes"

    // Hide the confirmation buttons
    btnSendYes.style.display = "none"
    btnSendNo.style.display  = "none"

    emailChoiceMsg.style.display = "block"
    emailChoiceMsg.textContent =
        "✅ Email will be sent after you complete and submit the report form."
    emailChoiceMsg.style.color = "var(--green)"
})


// ---- NO — skip email ----
btnSendNo.addEventListener("click", function () {
    sendEmailChoice.value = "no"

    btnSendYes.style.display = "none"
    btnSendNo.style.display  = "none"

    emailChoiceMsg.textContent = "✕ Email skipped."
    emailChoiceMsg.style.color = "var(--muted)"
    emailChoiceMsg.style.display = "block"
})


// ---- Clear image ----
function clearImage() {
    selectedFile = null
    imageInput.value = ""
    previewImg.src = ""
    imagePreview.style.display = "none"
    uploadInner.style.display = "flex"
    scanBox.style.display = "none"
    scanResult.style.display = "none"
    emailConfirmBox.style.display = "none"
    emailChoiceMsg.style.display = "none"
    uploadedFilename.value = ""
    scannedRoll.value  = ""
    scannedEmail.value = ""
    scannedName.value  = ""
    sendEmailChoice.value = ""
    hideFileSizeError()
    btnSendYes.style.display = "inline-flex"
    btnSendNo.style.display  = "inline-flex"
    btnSendYes.disabled = false
    btnSendNo.disabled  = false
    btnSendYes.textContent = "✅ Yes, Send Email"
}
