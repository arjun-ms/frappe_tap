import frappe
from frappe.utils.background_jobs import enqueue
from .glific_integration import optin_contact, start_contact_flow

def process_glific_actions(teacher_id, phone, first_name, school, school_name, language, model_name):
    try:
        # Optin the contact
        optin_success = optin_contact(phone, first_name)
        if not optin_success:
            frappe.logger().error(f"Failed to opt in contact for teacher {teacher_id}")
            return

        # Get the Glific ID
        glific_id = frappe.db.get_value("Teacher", teacher_id, "glific_id")
        if not glific_id:
            frappe.logger().error(f"Glific ID not found for teacher {teacher_id}")
            return

        # Start the "Teacher Web Onboarding Flow" in Glific
        flow = frappe.db.get_value("Glific Flow", {"label": "Teacher Web Onboarding Flow"}, "flow_id")
        if flow:
            default_results = {
                "teacher_id": teacher_id,
                "school_id": school,
                "school_name": school_name,
                "language": language,
                "model": model_name
            }
            flow_started = start_contact_flow(flow, glific_id, default_results)
            if flow_started:
                frappe.logger().info(f"Onboarding flow started for teacher {teacher_id}")
            else:
                frappe.logger().error(f"Failed to start onboarding flow for teacher {teacher_id}")
        else:
            frappe.logger().error("Glific flow not found")

    except Exception as e:
        frappe.logger().error(f"Error in process_glific_actions for teacher {teacher_id}: {str(e)}")

def enqueue_glific_actions(teacher_id, phone, first_name, school, school_name, language, model_name):
    enqueue(
        process_glific_actions,
        queue="short",
        timeout=300,
        teacher_id=teacher_id,
        phone=phone,
        first_name=first_name,
        school=school,
        school_name=school_name,
        language=language,
        model_name=model_name
    )
