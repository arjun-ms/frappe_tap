import frappe
import requests
import json
from datetime import datetime, timedelta,timezone
from dateutil.parser import isoparse



def get_glific_settings():
    return frappe.get_single("Glific Settings")


def get_glific_auth_headers():
    settings = get_glific_settings()
    current_time = datetime.now(timezone.utc)
    
    # Convert token_expiry_time to datetime if it's a string
    if settings.token_expiry_time:
        if isinstance(settings.token_expiry_time, str):
            settings.token_expiry_time = isoparse(settings.token_expiry_time)
        elif settings.token_expiry_time.tzinfo is None:
            settings.token_expiry_time = settings.token_expiry_time.replace(tzinfo=timezone.utc)
    
    if not settings.access_token or not settings.token_expiry_time or \
       current_time >= settings.token_expiry_time:
        # Token is expired or not set, get a new one
        url = f"{settings.api_url}/api/v1/session"
        payload = {
            "user": {
                "phone": settings.phone_number,
                "password": settings.password
            }
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()["data"]
            
            # Parse the token_expiry_time string to a timezone-aware datetime object
            token_expiry_time = isoparse(data["token_expiry_time"])
            
            # Update the Glific Settings directly in the database
            frappe.db.set_value("Glific Settings", settings.name, {
                "access_token": data["access_token"],
                "renewal_token": data["renewal_token"],
                "token_expiry_time": token_expiry_time
            }, update_modified=False)
            
            frappe.db.commit()
            
            return {
                "authorization": data["access_token"],
                "Content-Type": "application/json"
            }
        else:
            frappe.throw("Failed to authenticate with Glific API")
    else:
        return {
            "authorization": settings.access_token,
            "Content-Type": "application/json"
        }






def create_contact(name, phone, school_name, model_name, language_id):
    settings = get_glific_settings()
    url = f"{settings.api_url}/api"
    headers = get_glific_auth_headers()

    # Prepare the fields dictionary
    fields = {
        "school": {
            "value": school_name,
            "type": "string",
            "inserted_at": datetime.now(timezone.utc).isoformat()
        },
        "model": {
            "value": model_name,
            "type": "string",
            "inserted_at": datetime.now(timezone.utc).isoformat()
        },
        "buddy_name": {
            "value": name,
            "type": "string",
            "inserted_at": datetime.now(timezone.utc).isoformat()
        }

    }

    payload = {
        "query": "mutation createContact($input:ContactInput!) { createContact(input: $input) { contact { id name phone } errors { key message } } }",
        "variables": {
            "input": {
                "name": name,
                "phone": phone,
                "fields": json.dumps(fields),
                "languageId": int(language_id)
            }
        }
    }

    frappe.logger().info(f"Attempting to create Glific contact. Name: {name}, Phone: {phone}, School: {school_name}, Model: {model_name}, Language ID: {language_id}")
    frappe.logger().info(f"Glific API URL: {url}")
    frappe.logger().info(f"Glific API Headers: {headers}")
    frappe.logger().info(f"Glific API Payload: {payload}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        frappe.logger().info(f"Glific API response status: {response.status_code}")
        frappe.logger().info(f"Glific API response content: {response.text}")

        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                frappe.logger().error(f"Error creating Glific contact: {data['errors']}")
                return None
            if "data" in data and "createContact" in data["data"] and "contact" in data["data"]["createContact"]:
                contact = data["data"]["createContact"]["contact"]
                frappe.logger().info(f"Glific contact created successfully: {contact}")
                return contact
            else:
                frappe.logger().error(f"Unexpected response structure: {data}")
                return None
        else:
            frappe.logger().error(f"Failed to create Glific contact. Status code: {response.status_code}")
            return None
    except Exception as e:
        frappe.logger().error(f"Exception occurred while creating Glific contact: {str(e)}", exc_info=True)
        return None

def get_contact_by_phone(phone):
    settings = get_glific_settings()
    url = f"{settings.api_url}/api"
    headers = get_glific_auth_headers()
    payload = {
        "query": """
        query contactByPhone($phone: String!) {
          contactByPhone(phone: $phone) {
            contact {
              id
              name
              optinTime
              optoutTime
              phone
              bspStatus
              status
              lastMessageAt
              fields
              settings
            }
          }
        }
        """,
        "variables": {
            "phone": phone
        }
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            frappe.logger().error(f"Glific API Error in getting contact by phone: {data['errors']}")
            return None
        
        contact = data.get("data", {}).get("contactByPhone", {}).get("contact")
        if contact:
            return contact
        else:
            frappe.logger().error(f"Contact not found for phone: {phone}")
            return None
    except requests.exceptions.RequestException as e:
        frappe.logger().error(f"Error calling Glific API to get contact by phone: {str(e)}")
        return None

def optin_contact(phone, name):
    settings = get_glific_settings()
    url = f"{settings.api_url}/api"
    headers = get_glific_auth_headers()
    payload = {
        "query": """
        mutation optinContact($phone: String!, $name: String) {
          optinContact(phone: $phone, name: $name) {
            contact {
              id
              phone
              name
              lastMessageAt
              optinTime
              bspStatus
            }
            errors {
              key
              message
            }
          }
        }
        """,
        "variables": {
            "phone": phone,
            "name": name
        }
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            frappe.logger().error(f"Glific API Error in opting in contact: {data['errors']}")
            return False
        
        contact = data.get("data", {}).get("optinContact", {}).get("contact")
        if contact:
            frappe.logger().info(f"Contact opted in successfully: {contact}")
            return True
        else:
            frappe.logger().error(f"Failed to opt in contact. Response: {data}")
            return False
    except requests.exceptions.RequestException as e:
        frappe.logger().error(f"Error calling Glific API to opt in contact: {str(e)}")
        return False




def create_contact_old(name, phone):
    settings = get_glific_settings()
    url = f"{settings.api_url}/api"
    headers = get_glific_auth_headers()
    payload = {
        "query": "mutation createContact($input:ContactInput!) { createContact(input: $input) { contact { id name phone } errors { key message } } }",
        "variables": {
            "input": {
                "name": name,
                "phone": phone
            }
        }
    }

    frappe.logger().info(f"Attempting to create Glific contact. Name: {name}, Phone: {phone}")
    frappe.logger().info(f"Glific API URL: {url}")
    frappe.logger().info(f"Glific API Headers: {headers}")
    frappe.logger().info(f"Glific API Payload: {payload}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        frappe.logger().info(f"Glific API response status: {response.status_code}")
        frappe.logger().info(f"Glific API response content: {response.text}")

        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                frappe.logger().error(f"Error creating Glific contact: {data['errors']}")
                return None
            if "data" in data and "createContact" in data["data"] and "contact" in data["data"]["createContact"]:
                contact = data["data"]["createContact"]["contact"]
                frappe.logger().info(f"Glific contact created successfully: {contact}")
                return contact
            else:
                frappe.logger().error(f"Unexpected response structure: {data}")
                return None
        else:
            frappe.logger().error(f"Failed to create Glific contact. Status code: {response.status_code}")
            return None
    except Exception as e:
        frappe.logger().error(f"Exception occurred while creating Glific contact: {str(e)}", exc_info=True)
        return None







def start_contact_flow(flow_id, contact_id, default_results):
    settings = get_glific_settings()
    url = f"{settings.api_url}/api"
    headers = get_glific_auth_headers()
    payload = {
        "query": """
        mutation startContactFlow($flowId: ID!, $contactId: ID!, $defaultResults: Json!) {
            startContactFlow(flowId: $flowId, contactId: $contactId, defaultResults: $defaultResults) {
                success
                errors {
                    key
                    message
                }
            }
        }
        """,
        "variables": {
            "flowId": flow_id,
            "contactId": contact_id,
            "defaultResults": json.dumps(default_results)
        }
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            frappe.logger().error(f"Glific API Error in starting flow: {data['errors']}")
            return False
        
        success = data.get("data", {}).get("startContactFlow", {}).get("success")
        if success:
            return True
        else:
            frappe.logger().error(f"Failed to start Glific flow. Response: {data}")
            return False
    except requests.exceptions.RequestException as e:
        frappe.logger().error(f"Error calling Glific API to start flow: {str(e)}")
        return False


def update_student_glific_ids(batch_size=100):
    def format_phone(phone):
        phone = phone.strip().replace(' ', '')
        if len(phone) == 10:
            return f"91{phone}"
        elif len(phone) == 12 and phone.startswith('91'):
            return phone
        else:
            return None

    students = frappe.get_all(
        "Student",
        filters={"glific_id": ["in", ["", None]]},
        fields=["name", "phone"],
        limit=batch_size
    )

    for student in students:
        formatted_phone = format_phone(student.phone)
        if not formatted_phone:
            frappe.logger().warning(f"Invalid phone number for student {student.name}: {student.phone}")
            continue

        glific_contact = get_contact_by_phone(formatted_phone)
        if glific_contact and 'id' in glific_contact:
            frappe.db.set_value("Student", student.name, "glific_id", glific_contact['id'])
            frappe.logger().info(f"Updated Glific ID for student {student.name}: {glific_contact['id']}")
        else:
            frappe.logger().warning(f"No Glific contact found for student {student.name} with phone {formatted_phone}")

    frappe.db.commit()
    return len(students)


#! code generated by claude
def update_teacher_in_glific(contact_id, name, school_name, model_name, language_id, batch_name):
    """
    Updates a teacher's contact information in Glific.
    
    Args:
        contact_id (str): The Glific ID of the teacher's contact to update
        name (str): The teacher's name
        school_name (str): The name of the school
        model_name (str): The name of the TAP model
        language_id (str): The Glific language ID
        batch_name (str): The name of the batch
    
    Returns:
        dict: The updated contact information if successful, None if failed
    """
    try:
        # First verify this contact ID belongs to a teacher
        teacher = frappe.get_all(
            "Teacher",
            filters={"glific_id": contact_id},
            fields=["name"]
        )
        
        if not teacher:
            frappe.logger().error(f"Contact ID {contact_id} does not belong to any teacher")
            return None

        settings = get_glific_settings()
        url = f"{settings.api_url}/api"
        headers = get_glific_auth_headers()

        # Prepare the fields dictionary with current timestamp
        fields = {
            "school": {
                "value": school_name,
                "type": "string",
                "inserted_at": datetime.now(timezone.utc).isoformat()
            },
            "model": {
                "value": model_name,
                "type": "string",
                "inserted_at": datetime.now(timezone.utc).isoformat()
            },
            "buddy_name": {
                "value": name,
                "type": "string",
                "inserted_at": datetime.now(timezone.utc).isoformat()
            },
            "batch_name": {
                "value": batch_name,
                "type": "string",
                "inserted_at": datetime.now(timezone.utc).isoformat()
            },
            "contact_type": {  # Adding a type identifier
                "value": "teacher",
                "type": "string",
                "inserted_at": datetime.now(timezone.utc).isoformat()
            }
        }

        # GraphQL mutation for updating contact
        payload = {
            "query": """
            mutation updateContact($id: ID!, $input: ContactInput!) {
                updateContact(id: $id, input: $input) {
                    contact {
                        id
                        name
                        phone
                        fields
                        language {
                            id
                        }
                    }
                    errors {
                        key
                        message
                    }
                }
            }
            """,
            "variables": {
                "id": str(contact_id),
                "input": {
                    "name": name,
                    "fields": json.dumps(fields),
                    "languageId": int(language_id)
                }
            }
        }

        # Log the update attempt
        frappe.logger().info(
            f"Attempting to update teacher's Glific contact. ID: {contact_id}, "
            f"Name: {name}, School: {school_name}, Model: {model_name}, "
            f"Language ID: {language_id}, Batch: {batch_name}"
        )
        frappe.logger().info(f"Glific API URL: {url}")
        frappe.logger().info(f"Glific API Headers: {headers}")
        frappe.logger().info(f"Glific API Payload: {payload}")

        response = requests.post(url, json=payload, headers=headers)
        frappe.logger().info(f"Glific API response status: {response.status_code}")
        frappe.logger().info(f"Glific API response content: {response.text}")

        if response.status_code == 200:
            data = response.json()
            
            # Check for errors in the response
            if "errors" in data:
                frappe.logger().error(f"Error updating teacher's Glific contact: {data['errors']}")
                return None

            # Get the updated contact data
            update_data = data.get("data", {}).get("updateContact", {})
            
            # Check for errors in the mutation response
            if update_data.get("errors"):
                error_message = update_data["errors"][0].get("message", "Unknown error")
                frappe.logger().error(f"Teacher contact update failed: {error_message}")
                return None

            # Get the contact information
            contact = update_data.get("contact")
            if contact:
                frappe.logger().info(f"Teacher's Glific contact updated successfully: {contact}")
                return contact
            else:
                frappe.logger().error(f"No contact data in response: {data}")
                return None

        else:
            frappe.logger().error(
                f"Failed to update teacher's Glific contact. Status code: {response.status_code}"
            )
            return None

    except requests.exceptions.RequestException as e:
        frappe.logger().error(
            f"Request exception while updating teacher's Glific contact: {str(e)}", 
            exc_info=True
        )
        return None
    except Exception as e:
        frappe.logger().error(
            f"Unexpected error while updating teacher's Glific contact: {str(e)}", 
            exc_info=True
        )
        return None