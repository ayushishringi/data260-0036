const form = document.getElementById("vuln-form");

const createSubmissionCounter = () => {
  let count = 0;
  return () => {
    count += 1;
    return count;
  };
};

const nextSubmissionCount = createSubmissionCounter();

const validateSubmission = ({ description, agreedToTerms }) => {
  if (description.length <= 25) {
    alert("Description must be more than 25 characters.");
    return false;
  }
  if (!agreedToTerms) {
    alert("You must agree to the terms and conditions.");
    return false;
  }
  return true;
};

form.addEventListener("submit", (event) => {
  event.preventDefault();

  const formData = {
    packageName: document.getElementById("packageName").value.trim(),
    affectedVersion: document.getElementById("affectedVersion").value.trim(),
    submitterEmail: document.getElementById("submitterEmail").value.trim(),
    description: document.getElementById("description").value.trim(),
    severity: document.getElementById("severity").value,
    agreedToTerms: document.getElementById("agreedToTerms").checked,
  };

  if (!validateSubmission(formData)) {
    return;
  }

  const jsonString = JSON.stringify(formData);
  console.log("Form data as JSON string:");
  console.log(jsonString);

  const parsed = JSON.parse(jsonString);
  const { packageName, submitterEmail } = parsed;
  console.log("Primary field (packageName):", packageName);
  console.log("Email field (submitterEmail):", submitterEmail);

  const withDate = {
    ...parsed,
    submissionDate: new Date().toISOString(),
  };
  console.log("Parsed object with submissionDate:");
  console.log(withDate);

  const submissionCount = nextSubmissionCount();
  console.log("Successful submission count:", submissionCount);

  const output = document.getElementById("output");
  output.hidden = false;
  output.textContent = [
    "JSON string:",
    jsonString,
    "",
    "Primary field (packageName): " + packageName,
    "Email field (submitterEmail): " + submitterEmail,
    "",
    "Object with submissionDate:",
    JSON.stringify(withDate, null, 2),
    "",
    "Successful submission count: " + submissionCount,
  ].join("\n");

  alert(`Vulnerability report submitted (${submissionCount}). Check the console (and the output box) for JSON.`);
});
