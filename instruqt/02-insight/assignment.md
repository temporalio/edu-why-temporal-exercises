---
slug: insight
id: dacippgweizm
type: challenge
title: 'Exercise: Insight'
teaser: Look inside a running order and see exactly what happened to it, and why.
tabs:
- id: ua6ixhfbqcbj
  title: Chaos Panel
  type: service
  hostname: workshop
  path: /
  port: 8085
- id: wbzpad8scbqo
  title: Temporal Web UI
  type: service
  hostname: workshop
  path: /
  port: 8233
difficulty: basic
timelimit: 1800
enhanced_loading: null
---

In this exercise, you'll look at an order through the Temporal Web UI and see what it can tell you that the panel can't.

<details>
<summary style="width: fit-content; background: #444CE7; color: #FFFFFF; padding: 2px 10px; border-radius: 4px; margin-bottom: 6px; cursor: pointer">Why the Web UI</summary>
<div style="border-left: 3px solid #444CE7; padding-left: 12px; margin-bottom: 8px">

In the previous exercise, you watched an order survive everything you threw at it. The Chaos Panel showed you exactly what was happening because it was built to. A real application doesn't come with that visibility. When it's slow or failing, you piece the story together from logs spread across multiple systems.

Temporal records every step of a Workflow (the logic that carries an order from start to finish) as an event in its Event History, and the Temporal Web UI shows those events and the data they contain.

</div>
</details>

# Finding your order

In the [button label="Chaos Panel" background="#444CE7"](tab-0), place an order. Then open the [button label="Temporal Web UI" background="#444CE7"](tab-1).

Each order is a Workflow (the logic that carries an order from start to finish), and its Workflow ID is the order ID shown on the panel. If your order isn't in the list yet, click **Refresh**. Then click your order to open it.

![The Workflows list: the new order is at the top, Running, with the Refresh button highlighted](../assets/ui-workflows.png)

At the top are the order's status and how long it has run. Below that, **Input** shows what the order started with: the item and the amount to charge.

![The order's page in the Temporal Web UI: its status, its ID, and the order details it started with](../assets/ui-order.png)

# Asking the order where it is

<details>
<summary style="width: fit-content; background: #444CE7; color: #FFFFFF; padding: 2px 10px; border-radius: 4px; margin-bottom: 6px; cursor: pointer">What's a Query?</summary>
<div style="border-left: 3px solid #444CE7; padding-left: 12px; margin-bottom: 8px">

A Workflow can expose its state through a Query, which other applications, such as the Temporal Web UI, can call. Our order Workflow has a Query that reports its current step, which shows how far along the order is.

</div>
</details>

Let the order reach **Kitchen prep** on the panel, and leave it waiting there.

In the Temporal Web UI, open the **Queries** tab.

![The order's page, with the Queries tab highlighted](../assets/ui-queries-tab.png)

Select the **current_step** Query, and click **Run Query**.

![The Queries tab: the current_step query returns waiting_for_kitchen](../assets/ui-query.png)

The Query should return `waiting_for_kitchen`. The Chaos Panel uses the same approach to show the order's progress.

Return to the [button label="Chaos Panel" background="#444CE7"](tab-0) and click **Finish** on the kitchen and delivery to complete the order.

# Watching a failure as it happens

On the panel, switch off the Charge payment step, then place a new order. **Charge payment** shows **Retrying**, and the panel tells you the payment service is down. It doesn't show how many times it has tried, when it will try next, or what the error was.

In the [button label="Temporal Web UI" background="#444CE7"](tab-1), click **Back to Workflows**, open the new order, and click the **Pending Activities** tab. In this application, each call to an outside service is an Activity, so this tab shows the calls that haven't finished yet.

![Pending Activities while payment is down: attempt 7 of unlimited, the time of the next retry, and the error "payment service unreachable"](../assets/ui-pending-activities.png)

This is the view you'd want in a real outage:

- **Attempt** shows how many times the step has been tried.
- **Next Retry** shows when it will try again.
- **Last Failure** shows the actual error: `payment service unreachable: All connection attempts failed`.

Watch the page for a while, and the attempt count keeps climbing. Then switch the Charge payment step back on and let the order run to the kitchen.

# Finding the crash

With the order waiting at **Kitchen prep**, switch off the **Worker**. Click **Finish** on the kitchen while the Worker is down, wait a few seconds, then switch the Worker back on. Let the order run to completion.

# Reading the history

In the [button label="Temporal Web UI" background="#444CE7"](tab-1), open the completed order. The **Timeline** shows every service call as a bar.

![The Timeline: the charge_payment bar runs red to green with a retry count of 7, followed by the other steps and both Signals](../assets/ui-timeline.png)

The long **charge_payment** bar is the payment outage. It starts red while the step is failing, turns green when it succeeds, and shows how many attempts it took. The two pink markers are your **Finish** clicks, arriving as Signals.

Now open the **Event History** tab. Every service call appears as three events: scheduled, started and completed. The kitchen and delivery waits each appear as a single **Workflow Execution Signaled** event, when your **Finish** click arrives.

![The finished order's page, with the Event History tab highlighted](../assets/ui-history-tab.png)

The list starts with the newest event. Click **Descending**, above the list, to switch to oldest first, so it reads in the order things happened.

![The Event History heading, with the Descending button highlighted](../assets/ui-history-order.png)

<details>
<summary style="width: fit-content; background: #444CE7; color: #FFFFFF; padding: 2px 10px; border-radius: 4px; margin-bottom: 6px; cursor: pointer">Where are the failed attempts?</summary>
<div style="border-left: 3px solid #444CE7; padding-left: 12px; margin-bottom: 8px">

The failed attempts aren't listed one by one. Instead, the **Activity Task Started** event records which attempt finally worked, and the gap between the **Activity Task Scheduled** and **Activity Task Started** timestamps shows roughly how long the outage lasted. The **Activity Task Completed** event shows the result: the charge ID the payment service returned.

![Event History for the payment step: scheduled, then started on attempt 7, then completed with a charge ID](../assets/ui-history-payment.png)

</div>
</details>

Further down, find the crash:

![Event History around the crash: the kitchen Signal arrives, the task times out, and a Worker with a different identity picks the order up](../assets/ui-history-crash.png)

<details>
<summary style="width: fit-content; background: #444CE7; color: #FFFFFF; padding: 2px 10px; border-radius: 4px; margin-bottom: 6px; cursor: pointer">Reading the crash, event by event</summary>
<div style="border-left: 3px solid #444CE7; padding-left: 12px; margin-bottom: 8px">

Read it from the top:

1. **Workflow Task Completed:** the Worker finishes its last task before the crash. Note its **Identity**.
2. **Workflow Execution Signaled** (`order_prepared`): your kitchen Signal arrives while no Worker is running.
3. **Workflow Task Scheduled:** Temporal schedules the work.
4. **Workflow Task Timed Out:** Temporal tries to give the work to the same Worker, since it already has the order in memory. But that Worker has been killed, so after a few seconds, the task times out.
5. **Workflow Task Scheduled:** Temporal schedules the work again, this time for any available Worker.
6. **Workflow Task Started:** now that the Worker has been restarted, it picks up the work.
7. **Workflow Task Completed:** the new Worker completes the work. Its **Identity** is different, because it's a new instance.

</div>
</details>

# What the UI doesn't show

The Temporal Web UI shows what the Workflow did. What happens inside each service is that service's job, and Temporal deliberately stays out of it. It doesn't know whether a customer was charged once or twice.

<details>
<summary style="width: fit-content; background: #444CE7; color: #FFFFFF; padding: 2px 10px; border-radius: 4px; margin-bottom: 6px; cursor: pointer">Why Temporal doesn't track the ledgers</summary>
<div style="border-left: 3px solid #444CE7; padding-left: 12px; margin-bottom: 8px">

By default, Temporal retries a failed step until it succeeds, but how a retry should behave depends on the business. Here, the business requires that we don't charge the same card twice, but in other cases, repeating an action might be the desired result. So it's up to the developer to decide how a retry behaves and what information it exposes. In the Chaos Panel, we deliberately exposed each service's ledger on the panel.

</div>
</details>

# Try your own experiments

Try your own scenarios. Explore the UI, break the Workflow, and see how the Temporal Web UI responds. At each stage, Temporal shows you what went wrong, while making sure the work isn't lost.