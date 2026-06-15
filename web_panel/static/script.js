/**
 * script.js
 * Handles dynamic interactions for the CompassVPN Agent Configuration Panel.
 */

// Generic handler for conditional fields based on data attributes
// Shows/hides dependent fields and manages their 'required' attribute
function handleConditionChange(triggerElement) {
    const triggerValue = (triggerElement.type === 'checkbox' || triggerElement.type === 'radio') ? (triggerElement.checked ? triggerElement.value : null) : triggerElement.value;
    const triggerName = triggerElement.name;
    const isChecked = triggerElement.checked;

    document.querySelectorAll(`.conditional-field[data-condition-field="${triggerName}"]`).forEach(dependentField => {
        const conditionValue = dependentField.getAttribute('data-condition-value');
        let conditionMet = false;
        let isVisible = false;

        if (triggerElement.type === 'checkbox' && triggerElement.role === 'switch') {
             conditionMet = isChecked && (conditionValue === triggerElement.value);
        } else {
             conditionMet = triggerValue === conditionValue;
        }

        if (conditionMet) {
            dependentField.style.display = 'block';
            isVisible = true;
        } else {
            dependentField.style.display = 'none';
            isVisible = false;
        }

        // UPDATED: All inputs will have required attribute unless hidden
        // (excluding toggle switches, hidden inputs, and custom DNS text when appropriate)
        dependentField.querySelectorAll('input:not([role="switch"]):not([type="hidden"]), select, textarea').forEach(input => {
            if (!isVisible) {
                input.removeAttribute('required');
            } else if (!(input.classList.contains('custom-dns-text-input') && !document.getElementById('CUSTOM_DNS').value === 'custom')) {
                input.setAttribute('required', '');
            }
        });
    });

    // Update hidden input state for toggles (to submit correct off_value)
    if (triggerElement.type === 'checkbox' && triggerElement.role === 'switch') {
        const hiddenInput = triggerElement.parentElement.querySelector('input[type="hidden"][name="' + triggerName + '"]');
        if (hiddenInput) {
            hiddenInput.disabled = isChecked;
        }
    }
}

// Specific toggle for CUSTOM_DNS select to show/hide/require the text input
function toggleCustomDnsText(selectElement) {
     var customInput = document.querySelector('.custom-dns-text-input');
     if (selectElement && customInput) {
         const isCustomSelected = selectElement.value === 'custom';
         customInput.style.display = isCustomSelected ? 'block' : 'none';
         // Set required attribute based on visibility
         if (isCustomSelected) {
            customInput.setAttribute('required', '');
         } else {
            customInput.removeAttribute('required');
            customInput.setCustomValidity(''); // Clear validation if hidden
         }
     }
 }

// Confirmation dialog for potentially disruptive actions
// Also checks form validity before allowing submission
function confirmAction(actionType, form) {
    let message = "Are you sure?";
    if (actionType === 'save_close') {
        message = "This will save the configuration and STOP the web panel.\n\nTo reopen, run ./start_panel.sh in server terminal.\n\nProceed?";
    } else if (actionType === 'save_close_bootstrap') {
        message = "This will save the configuration, STOP the web panel, and trigger the relevant start/restart script.\n\nTo reopen, run ./start_panel.sh in server terminal.\n\nProceed?";
    }

    const confirmed = confirm(message);

    if (confirmed) {
        const isValid = form.checkValidity();
        // Check HTML5 form validity AFTER confirmation
        if (!isValid) {
            // If invalid, explicitly trigger browser validation UI and prevent submission
            form.reportValidity();
            return false;
        }
        // If valid, allow submission
        return true;
    } else {
        // If user cancelled confirmation, prevent submission
        return false;
    }
}

// Validation: Ensure at least one inbound checkbox is selected
function validateInbounds() {
    const inboundCheckboxes = document.querySelectorAll('.inbound-checkbox');
    const firstCheckbox = inboundCheckboxes[0]; // Target the first checkbox for the validity message
    let isChecked = false;

    inboundCheckboxes.forEach(checkbox => {
        if (checkbox.checked) {
            isChecked = true;
        }
    });

    if (firstCheckbox) { // Ensure the checkbox exists
        if (!isChecked) {
            firstCheckbox.setCustomValidity('Please select at least one inbound protocol.');
        } else {
            firstCheckbox.setCustomValidity(''); // Clear the message if valid
        }
    }
}

// Validation: Check format for NGINX_FAKE_WEBSITE and CF_CLEAN_IP_DOMAIN using regex
function validateSpecificFields() {
    const nginxInput = document.getElementById('NGINX_FAKE_WEBSITE');
    const cfCleanIpInput = document.getElementById('CF_CLEAN_IP_DOMAIN');

    // Regex for domain/subdomain without protocol
    const domainRegex = /^(?!https?:\/\/)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;
    // Regex for IPv4 address
    const ipv4Regex = /^((25[0-5]|(2[0-4]|1[0-9]|[1-9])?[0-9])\.){3}(25[0-5]|(2[0-4]|1[0-9]|[1-9])?[0-9])$/;

    if (nginxInput) {
        // Check only if value is not empty (required validation handles empty)
        if (nginxInput.value !== '' && !domainRegex.test(nginxInput.value)) {
            nginxInput.setCustomValidity('Please enter a valid domain or subdomain (e.g., example.com) without http:// or https://');
        } else {
            nginxInput.setCustomValidity('');
        }
    }

    if (cfCleanIpInput) {
        const value = cfCleanIpInput.value;
        // Check only if value is not empty (required validation handles empty)
        if (value !== '') {
            const isValidDomain = domainRegex.test(value);
            const isValidIp = ipv4Regex.test(value);
            if (!isValidDomain && !isValidIp) {
                cfCleanIpInput.setCustomValidity('Please enter a valid domain/subdomain (without http/https) OR a valid IPv4 address.');
            } else {
                cfCleanIpInput.setCustomValidity('');
            }
        } else {
             cfCleanIpInput.setCustomValidity(''); // Clear if empty
        }
    }
}

// Initialize checkboxes in a group to not be individually required
function initializeCheckboxGroups() {
    // Remove required attribute from individual checkboxes, as we use custom validation
    document.querySelectorAll('.inbound-checkbox').forEach(checkbox => {
        checkbox.removeAttribute('required');
    });
    
    // Run initial validation to ensure proper state
    validateInbounds();
}

// --- Initialization on Page Load ---
document.addEventListener('DOMContentLoaded', function() {

    // Initialize checkbox groups first
    initializeCheckboxGroups();

    // 1. Initialize all conditional field visibility and 'required' states
    //    Find all elements that trigger conditional changes and run the handler.
    document.querySelectorAll('select[onchange^="handleConditionChange"], input[type="checkbox"][onchange^="handleConditionChange"]').forEach(trigger => {
        handleConditionChange(trigger);
    });

    // NEW: Make sure all visible non-conditional inputs are also required
    document.querySelectorAll('input:not([role="switch"]):not([type="hidden"]):not(.custom-dns-text-input):not([type="checkbox"]), select:not(.custom-select), textarea').forEach(input => {
        // Only set required if the parent element is visible and not a conditional field
        const parentContainer = input.closest('.mb-3');
        if (parentContainer && 
            !parentContainer.classList.contains('conditional-field') && 
            window.getComputedStyle(parentContainer).display !== 'none') {
            input.setAttribute('required', '');
        }
    });

    // 2. Initialize visibility for specific complex toggles
    var customDnsSelect = document.getElementById('CUSTOM_DNS');
    if (customDnsSelect) {
        toggleCustomDnsText(customDnsSelect); // Custom DNS text input
    }

    // 3. Run initial validations
    validateInbounds(); // Check if at least one inbound is selected
    validateSpecificFields(); // Check format for domain/IP fields

    // --- Handle Advanced Settings Collapse ---
    const advancedCollapseElement = document.getElementById('collapse-advanced-settings');
    const headerButton = document.querySelector('.btn-header-toggle');
    const toggleText = headerButton?.querySelector('.toggle-text');
    const toggleIcon = headerButton?.querySelector('.toggle-icon');

    if (headerButton && advancedCollapseElement) {
        console.log('Found required elements for collapse handling');
        
        // Remove temporary debugging alert
        headerButton.addEventListener('click', function(e) {
            // Direct toggle of visibility
            if (advancedCollapseElement.classList.contains('show')) {
                // Hide it
                advancedCollapseElement.classList.remove('show');
                if (toggleText) toggleText.textContent = 'Show';
                if (toggleIcon) {
                    toggleIcon.classList.remove('bi-chevron-up');
                    toggleIcon.classList.add('bi-chevron-down');
                }
            } else {
                // Show it
                advancedCollapseElement.classList.add('show');
                if (toggleText) toggleText.textContent = 'Hide';
                if (toggleIcon) {
                    toggleIcon.classList.remove('bi-chevron-down');
                    toggleIcon.classList.add('bi-chevron-up');
                }
            }
        });
    } else {
        console.error('Could not find required elements for collapse handling:', {
            collapseElement: !!advancedCollapseElement,
            button: !!headerButton
        });
    }
});
