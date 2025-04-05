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

        // Add/Remove 'required' on child inputs/selects/textareas based on visibility,
        // EXCLUDING the custom DNS text input (handled separately).
        dependentField.querySelectorAll('input[type="text"]:not(.custom-dns-text-input), input[type="password"], select, textarea').forEach(input => {
            if (isVisible) {
                input.setAttribute('required', '');
            } else {
                input.removeAttribute('required');
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

// Specific toggle for Metric fields (Grafana vs Pushgateway)
function toggleMetricFields() {
    var select = document.getElementById('METRIC_PUSH_METHOD');
    var grafanaFields = document.querySelectorAll('.grafana-fields');
    var pushgatewayFields = document.querySelectorAll('.pushgateway-fields');

    if (select && grafanaFields.length > 0 && pushgatewayFields.length > 0) {
        const showGrafana = select.value === 'grafana_agent';
        // Simplified logic: Show pushgateway fields if grafana is not selected
        grafanaFields.forEach(el => el.style.display = showGrafana ? 'block' : 'none');
        pushgatewayFields.forEach(el => el.style.display = !showGrafana ? 'block' : 'none');
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

// --- Initialization on Page Load ---
document.addEventListener('DOMContentLoaded', function() {

    // 1. Initialize all conditional field visibility and 'required' states
    //    Find all elements that trigger conditional changes and run the handler.
    document.querySelectorAll('select[onchange^="handleConditionChange"], input[type="checkbox"][onchange^="handleConditionChange"]').forEach(trigger => {
        handleConditionChange(trigger);
    });

    // 2. Initialize visibility for specific complex toggles
    toggleMetricFields(); // Grafana vs Pushgateway

    var customDnsSelect = document.getElementById('CUSTOM_DNS');
    if (customDnsSelect) {
        toggleCustomDnsText(customDnsSelect); // Custom DNS text input
    }

    // 3. Run initial validations
    validateInbounds(); // Check if at least one inbound is selected
    validateSpecificFields(); // Check format for domain/IP fields

}); 
