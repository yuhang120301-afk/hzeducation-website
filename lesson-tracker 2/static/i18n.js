/* Translate interface nodes only. Authored content is marked data-user-content. */
(() => {
 const messages = {
"我的课程":"My lessons",
"按学生课时状态筛选":"Filter by student credit status",
"正常（课时不少于 3 节）":"Normal (at least 3 credits)",
"需续费（课时不足 3 节）":"Top-up needed (below 3 credits)",
"输入学生姓名、课程或家长手机号":"Search by student name, course or parent phone",
"没有找到匹配的学生。":"No matching students found.",
"已选学生：":"Selected students: ",
"删除并归档":"Archive student",
"删除并归档学生":"Archive student profile",
"已归档学生":"Archived students",
"恢复档案":"Restore profile",
"恢复学生档案":"Restore student profile",
"确认归档":"Confirm archive",
"暂无已归档学生。":"No archived students.",
"学生档案已恢复。":"Student profile restored.",
"学生已归档，可在已归档学生中恢复。":"Student archived. You can restore the profile from Archived students.",
"归档后从日常学生列表和新排课选项中移除。所有科目的课时、赠送课时和历史记录保留，已有排课不会自动取消。":"Archiving removes the student from active lists and new lesson choices. All subject balances, gift credits and records are retained. Existing lessons are not automatically cancelled.",
"老板可在已归档学生中恢复。":"The owner can restore the profile from Archived students.",
"恢复后重新显示在学生列表中，可以排课和充值；原余额及记录保留。":"Restoring returns the student to active lists for scheduling and top-ups. Existing balances and records are retained.",
"删除档案":"Delete profile",
"删除学生档案":"Delete student profile",
"删除老师档案":"Delete teacher profile",
"删除管理员档案":"Delete administrator profile",
"确认删除":"Confirm deletion",
"档案已删除。":"Profile deleted.",
"只有老板可以删除档案。":"Only the owner can delete profiles.",
"仅可删除没有课时余额、课程或业务记录的档案。会删除这位学生名下所有空白科目，家长账号保留。":"Only unused profiles with no credits, lessons or business records can be deleted. All empty subject accounts for this student will be removed. The guardian account is retained.",
"仅可删除没有课时余额、课程或业务记录的档案。删除后该账号无法登录。":"Only unused profiles with no credits, lessons or business records can be deleted. The account will no longer be able to sign in.",
"删除后无法恢复，请确认不是仍需使用的档案。":"Deletion cannot be undone. Make sure this profile is no longer needed.",
"请续费":"Please top up",
"需要续费":"Top-up needed",
"至少一个科目的课时不足 3 节，请续费":"Fewer than 3 credits in at least one subject. Please top up.",
"课时用完后再使用赠送课时。课时不足 3 节时提醒续费。":"Gift credits are used after regular credits run out. A top-up reminder appears below 3 regular credits.",
"原有课时":"Existing credits",
"退回课时":"Credits to refund",
"没有可退的课时，赠送课时不可退款。":"No refundable credits. Gift credits cannot be refunded.",
"付费课时":"Paid credits",
"赠送课时":"Gift credits",
"先扣完该科目的付费课时，再扣赠送课时。退费时，该充值批次剩余赠课全部作废。":"Paid credits for this subject are used first. Refunding a purchase voids its remaining gift credits.",
"赠送课时不计入收款金额；纯赠课填写 0。":"Gift credits are excluded from the payment. Enter 0 for a gift-only top-up.",
"充值批次":"Purchase batch",
"退回付费课时":"Paid credits to refund",
"确认退费并作废赠课":"Confirm refund and void gifts",
"退费已记录，对应批次剩余赠课已作废。":"Refund recorded and remaining gifts from the selected batch voided.",
"没有可退的付费课时，赠送课时不可退款。":"No paid credits available to refund. Gift credits are not refundable.",
"充值及赠课":"Paid and gift top-ups",
"赠课作废":"Voided gift credits",
"退付费课时":"Refunded paid credits",
"历史余额（未拆分）":"Legacy balance (not separated)",
"请选择要退费的充值批次。":"Select the purchase batch to refund.",
"退款课时不能超过该批次剩余付费课时，赠送课时不可退款。":"Refunds cannot exceed the selected batch\u2019s remaining paid credits. Gifts are not refundable.",
 '编辑老师':'Edit teacher','编辑教学科目':'Edit subjects','在职':'Active','已离职 / 停用':'Departed / inactive',
 '离职 / 停用':'Mark departed / disable','恢复在职':'Reactivate','教学科目 · 可多选':'Teaching subjects · Select multiple',
 '更多科目可在课程与地点设置中添加。':'Add more subjects in Courses & locations.',
 '此账号兼任管理职务，这里仅修改教学科目。':'This account also has management access. Edit teaching subjects here.',
 '保存老师':'Save teacher','老师资料已保存。':'Teacher saved.','老师状态已更新。':'Teacher status updated.',
 '仍有未完成课程，请查看课表并调整任课老师。':'Unfinished lessons remain. Review the timetable and reassign the teacher.',
 '离职停用后无法登录或接受新排课，历史课程和课后记录保留。':'Inactive teachers cannot sign in or receive new lessons. Past lessons and reports remain.',
 '停用后无法登录或接受新排课。已有课程保留，请另行调整未完成课程。':'Disabling blocks sign-in and new bookings. Existing lessons remain; reassign unfinished lessons.',
 '恢复后可使用原账号登录并接受排课。':'Reactivation restores sign-in and scheduling.',
 '留空保留原密码；修改手机号或密码后需重新登录。':'Leave blank to keep the password. Phone or password changes require a new sign-in.',
 '至少 10 位，请单独告知老师。':'At least 10 characters. Share privately with the teacher.',
 '请选择 1–20 个教学科目。':'Select 1–20 teaching subjects.',

 '编辑管理员':'Edit administrator','管理员资料已更新。':'Administrator updated.',
 '留空则保留原密码。修改登录手机号或重置密码后，管理员需重新登录。':'Leave blank to keep the password. Changing the login phone or password signs the administrator out.',
 '请选择有效的管理员。':'Select a valid administrator.',

"编辑档案":"Edit profile",
"家长账号":"Parent account",
"添加科目":"Add subject",
"添加学生科目":"Add student subject",
"编辑学生档案":"Edit student profile",
"保存档案":"Save profile",
"生日":"Date of birth",
"年级":"Year level",
"内部备注":"Internal notes",
"仅老板和管理员可查看":"Visible only to the owner and administrators",
"例如：Year 8":"e.g. Year 8",
"年级未填写":"Year level not set",
"编辑家长账号":"Edit parent account",
"家长姓名":"Parent name",
"登录手机号":"Login phone number",
"联系手机号（选填）":"Contact phone (optional)",
"重置密码（选填）":"Reset password (optional)",
"保存家长账号":"Save parent account",
"留空则保留原密码。修改登录手机号或重置密码后，家长需重新登录。":"Leave blank to keep the password. Changing the login phone or password signs the parent out.",
"学生档案已更新。":"Student profile updated.",
"家长账号已更新。":"Parent account updated.",
"没有可添加的科目，请先在课程与地点设置中添加课程。":"No subjects available. Add a course in Courses & locations first.",
"新科目已添加，可单独充值课时。":"Subject added. Credits can be purchased separately.",
"各科课时独立计算":"Separate credits for each subject",
"至少一个科目剩余不超过 2 课时":"At least one subject has 2 credits or fewer",
"选择学生及扣课科目 · 同一学生只选一个科目":"Select students and subjects to charge \u00b7 One subject per student",
"请输入有效的出生日期。":"Enter a valid date of birth.",
"出生日期需在 1900 年至今天之间。":"Date of birth must be between 1900 and today.",
"这位学生已有关联课程，无需重复添加。":"This student is already enrolled in that subject.",
"同一节课，每位学生只能选择一个扣课科目。":"Select only one subject per student for each lesson.",
"此登录手机号已被其他账号使用。":"This login phone number is already used by another account.",
"请选择已启用的课程。":"Select an active course.",
"只有老板或管理员可以编辑学生档案。":"Only owners and administrators can edit student profiles.",
"课程与地点设置":"Courses & locations",
"管理排课时可选择的课程名称和上课地点。":"Manage course and location choices for scheduling.",
"添加后即可在排课时选择。修改或停用选项不会更改已排课程的名称和地点。":"Added options are available when scheduling. Editing or disabling them does not change existing lessons.",
"添加课程":"Add course",
"添加地点":"Add location",
"上课地点":"Location",
"编辑选项":"Edit option",
"保存选项":"Save option",
"选项已保存。":"Option saved.",
"选项已更新。":"Option updated.",
"请选择课程":"Select a course",
"不指定地点":"No location specified",
"尚未设置，请点击添加。":"No options yet. Add one to get started.",
"启用":"Enable",
"停用":"Disable",
"编辑":"Edit",
"例如：物理、化学、数学小班":"e.g. Physics, Chemistry, Small-group maths",
"例如：教室 A、线上 Zoom":"e.g. Room A, Online Zoom",
 '时间':'Time','＋ 排课':'+ Schedule','老师只能为自己的学生安排自己的课程。':'Teachers can only schedule their own lessons with their assigned students.',
 '重复安排':'Repeat','不重复':'Does not repeat','每周重复':'Every week','每两周重复':'Every two weeks','总课次数（包含本次）':'Total lessons (including this one)',
 '调整或取消仅影响本次课程。':'Changes or cancellation apply to this lesson only.',
 '按机构当地时间重复，最多 52 次。每次课程可单独调整或取消；如有冲突，本次全部不保存。':'Repeat at the same local school time, up to 52 lessons. Edit or cancel each lesson individually. If any lesson conflicts, none will be saved.',
 '重复选项无效。':'Invalid repeat option.','总课次数需为 2–52 次，包含本次。':'Enter 2–52 lessons, including this one.','调整课程仅修改本次课程。':'Edits apply to this lesson only.',

 '学习理念':'Our approach to learning','培养良好习惯':'Build lasting habits','掌握学习方法':'Learn effective methods','成就每一步成长':'Celebrate every step forward',
 '实际退款金额（AUD）':'Actual refund (AUD)','实际收款金额（AUD）':'Actual receipt (AUD)',
 '填写记录 →':'Write report →','继续草稿 →':'Continue draft →','· 管理员 / 任课老师':'· Administrator / teacher','· 任课老师':'· Teacher',
 '课时管理':'Lesson management','正在打开课时簿…':'Opening the learning portal…',
 '每一节，都有记录':'Every lesson, recorded','探索学习的乐趣，':'Discover the joy of learning,','见证每一步成长。':'grow with every step.',
 '查看课程安排、学习内容与今日作业，':'See lesson plans, learning notes and homework,','让每一次进步都有记录。':'with a record of every step forward.',
 '剩余课时 · 界面示例':'Remaining credits · example','上课记录':'Lesson record','课程安排 · 今日作业 · 课后反馈':'Schedule · Homework · Feedback',
 '登录学习中心':'Sign in to the Learning Centre','使用老师为你开通的手机号和密码登录。':'Use the phone number and password provided by your school.',
 '手机号':'Phone number','密码':'Password','登录':'Sign in','例如 +61 412 345 678':'e.g. +61 412 345 678','请输入密码':'Enter your password',
 '首次登录或忘记密码，请联系老师。':'Contact your school for a new account or password help.','手机号格式请与老师开通账号时保持一致。':'Use the same phone-number format as your registered account.',
 '当前是本机演示版，仅含虚构学生，可体验完整流程。':'Local demo with fictional students. Explore all roles below.',
 '老板':'Owner','管理员':'Administrator','任课老师':'Teacher','家长端':'Parent','家长':'Parent','老师中心':'Teacher portal','家长中心':'Parent portal','机构管理':'School management',
 '本机演示版 · 虚构数据 · 可分别体验老板、管理员、任课老师和家长账号':'Local demo · Fictional data · Explore owner, administrator, teacher and parent accounts',
 '把每一次进步，认真记下来。':'A thoughtful record of every step forward.',
 '账目总结':'Reconciliation','核对收款、退款与课时变动，每笔数字都有明细。':'Review receipts, refunds and lesson credits with transaction-level details.',
 '由老板开通管理员账号，分工管理机构日常事务。':'Create administrator accounts to manage daily school operations.',
 '排课日历':'Lesson calendar','我的课表':'My schedule','孩子的课表':'My child’s schedule','课后记录':'Lesson reports','学生与课时':'Students & credits','我的学生':'My students','剩余课时':'Remaining credits','课时明细':'Credit history','老师管理':'Teachers',
 '记录学习内容、今日作业和课后反馈。':'Record learning content, homework and feedback.','查看孩子每节课的学习内容、作业与老师反馈。':'See what your child learned, their homework and teacher feedback.',
 '查看学生余额，管理每一笔课时。':'View student balances and manage lesson credits.','剩余课时与学习记录，随时查看。':'Check remaining credits and learning records at any time.',
 '每一笔课时变动，均有记录可查。':'Every credit change has a clear record.','为任课老师开通独立账号，并安排课程。':'Create individual teacher accounts and assign lessons.',
 '修改密码':'Change password','退出':'Sign out','添加管理员':'Add administrator','添加老师':'Add teacher','添加学生':'Add student','新增排课':'Schedule lesson',
 '学生剩余课时合计':'Total student credits','孩子剩余课时合计':'Total remaining credits','以实际课时账本为准':'Based on the credit ledger','关联学生':'Assigned students','关联孩子':'Linked children',
 '可在课表中查看课程安排':'See scheduled lessons in the calendar','仅显示自己孩子的信息':'Only your children’s details are shown','课时较少':'Low balance','剩余不超过 2 课时':'2 credits or less remaining','学生课时':'Student credits',
 '搜索学生、课程或手机号':'Search student, course or phone','搜索学生':'Search students','最近课时记录':'Recent credit changes','全部记录 →':'View all →','课时变动记录':'Credit transactions','全部学生':'All students','按学生筛选':'Filter by student',
 '已排课不会提前扣课时。完成课程后才扣除；撤销会保留原记录。':'Scheduling does not deduct credits. Credits are deducted after completion, and reversals retain the original record.',
 '学生':'Student','课程':'Course','状态':'Status','操作':'Actions','课时':'credits','小时':'hours','位':'students','节':'lessons','余额充足':'Sufficient balance','正常':'Normal','剩余':'Remaining','查看课时明细 →':'View credit history →',
 '还没有关联的学生，请联系老师。':'No student is linked yet. Please contact your school.','排课':'Schedule','充值':'Top up','明细':'History','退课退款':'Withdraw & refund','没有匹配的学生。':'No matching students.','还没有学生，点击「添加学生」开始。':'No students yet. Select “Add student” to begin.',
 '日期 / 学生':'Date / student','类型':'Type','课时变动':'Credit change','备注':'Note','登记人 / 操作':'Recorded by / actions','登记人':'Recorded by','上课扣除':'Lesson deduction','课时充值':'Credit top-up','撤销返还 / 扣回':'Reversal','已撤销':'Reversed','撤销':'Reverse','暂无课时变动记录。':'No credit transactions yet.',
 '关闭':'Close','取消':'Cancel','登记上课':'Record a lesson','扣除课时':'Credits to deduct','充值课时':'Credits added','上课日期':'Lesson date','充值日期':'Payment date','备注（选填）':'Note (optional)','确认扣除':'Confirm deduction','确认充值':'Confirm top-up',
 '例如：补录历史课时':'e.g. Record a past lesson','例如：新学期购买 10 课时':'e.g. Purchase 10 credits for the new term','上课已登记，课时已扣除。':'Lesson recorded and credits deducted.','课时已充值。':'Credits added.','请先添加学生。':'Add a student first.',
 '学生姓名':'Student name','例如：陈一诺':'e.g. Alex Chen','课程名称':'Course name','例如：数学 · 一对一':'e.g. Mathematics · Private lesson','家长手机号':'Parent phone number','同一手机号可关联多个孩子。已有账号会直接关联。':'One parent account can link multiple children. Existing accounts are linked automatically.',
 '家长初始密码':'Initial parent password','新账号需至少 10 位':'At least 10 characters for a new account','已有家长账号可留空，其原密码保持不变。请单独告知家长登录信息。':'Leave blank for an existing parent; their password stays unchanged. Share new login details privately.',
 '创建学生':'Create student','学生已添加，可在列表中充值课时。':'Student added. You can now add credits.','撤销这笔记录？':'Reverse this transaction?','撤销原因':'Reason for reversal','例如：重复登记，返还课时':'e.g. Duplicate entry; restore credits','确认撤销':'Confirm reversal','已撤销，课时余额已更新。':'Transaction reversed and credit balance updated.',
 '当前密码':'Current password','新密码':'New password','至少 10 位，修改成功后需重新登录。':'At least 10 characters. You will need to sign in again.','保存新密码':'Save password','密码已修改，请重新登录。':'Password changed. Please sign in again.',
 '待上课':'Scheduled','已完成':'Completed','已取消':'Cancelled','待写课后记录':'Report due','本周课程':'Lessons this week','已安排 · 不含取消课程':'Scheduled, excluding cancellations','课后记录已发布':'Lesson reports published','已授课时长':'Teaching hours','已完成课程时长':'Completed lesson hours','按实际课程时段统计，与扣课单位分开':'Based on lesson duration, separate from credit deductions',
 '上一周':'Previous week','下一周':'Next week','本周':'This week','全部老师':'All teachers','按老师筛选':'Filter by teacher','按课程状态筛选':'Filter by status','全部状态':'All statuses','待上课 / 待记录':'Scheduled / report due','周一':'Mon','周二':'Tue','周三':'Wed','周四':'Thu','周五':'Fri','周六':'Sat','周日':'Sun','今天':'Today','暂无课程':'No lessons',
 '管理员 / 任课老师':'Administrator / teacher','待完成':'Pending','查看课表 →':'View schedule →','老师使用独立手机号登录，仅可查看自己的课表、关联学生及自己填写的课后记录。':'Teachers sign in individually and can only see their schedule, assigned students and their lesson reports.',
 '添加任课老师':'Add teacher','老师姓名':'Teacher name','例如：Emma 老师':'e.g. Emma','教学科目':'Subject','登录手机号':'Sign-in phone number','初始密码':'Initial password','老师可以登录后修改。请使用独立手机号，不与家长账号共用。':'Teachers can change their password after sign-in. Use a separate phone number from parent accounts.',
 '开通老师账号':'Create teacher account','老师账号已开通，可以开始排课。':'Teacher account created. You can now schedule lessons.','请先添加学生，再安排课程。':'Add students before scheduling a lesson.','调整课程':'Reschedule lesson','开始时间':'Start time','结束时间':'End time','预计扣课（每位学生）':'Planned credits per student','上课地点（选填）':'Location (optional)','教室或线上会议名称':'Classroom or online meeting name','选择学生 · 可多选安排小班课':'Select students · Choose multiple for a group lesson','保存排课':'Save schedule','课程已更新。':'Lesson updated.','排课已保存，课时暂不扣除。':'Lesson scheduled. No credits have been deducted.',
 '地点未填写':'Location not specified','取消原因：':'Cancellation reason:','本次课程未扣课时。':'No credits were deducted for this lesson.','已保存课后记录草稿，家长暂不可见。':'A draft is saved. It is not yet visible to parents.','完成课程后，填写学习内容、作业和反馈，再确认扣课。':'After the lesson, record learning content, homework and feedback, then confirm completion.',
 '课程结束后，老师会在这里发布学习内容、作业与反馈。':'The teacher will publish learning content, homework and feedback after the lesson.','调整排课':'Reschedule','取消课程':'Cancel lesson','修改课后记录':'Edit lesson report','填写课后记录':'Write lesson report','取消这节课':'Cancel this lesson','取消后保留课程记录，不扣课时。':'The schedule remains recorded, with no credit deduction.','取消原因':'Cancellation reason','例如：学生请假，另约时间':'e.g. Student unavailable; reschedule later','确认取消课程':'Confirm cancellation','课程已取消，没有扣课时。':'Lesson cancelled. No credits deducted.',
 '本次扣除课时':'Credits for this lesson','已完成课程的课时不可在此修改；本次保存不会再次扣课。':'Credits cannot be changed here after completion. Saving will not deduct them again.','学习内容':'Learning content','今日作业':'Homework','课后反馈':'Teacher feedback','例如：分数加减法，通分与约分的应用。':'e.g. Adding and subtracting fractions; common denominators and simplification.','例如：完成练习册第 12 页 1–6 题；没有作业请写“今日无作业”。':'e.g. Workbook page 12, questions 1–6. Enter “No homework” if none is assigned.','记录掌握情况、课堂表现，以及下次课需要加强的内容。':'Note understanding, participation and areas to practise next time.',
 '保存后更新家长端，课时不会再次扣除。':'Parents will see the updated report. Credits will not be deducted again.','保存草稿不会扣课，也不会向家长展示。确认完成后将扣除课时并发布给家长。':'Drafts do not deduct credits and are hidden from parents. Completing the lesson deducts credits and publishes the report.',
 '保存修改':'Save changes','确认完成并扣课':'Complete & deduct credits','课后记录已更新，没有重复扣课。':'Report updated. No additional credits deducted.','课程已完成，课时已扣除，家长可以查看课后记录。':'Lesson completed and credits deducted. The report is now visible to parents.','保存草稿':'Save draft','草稿已保存，未扣课时。':'Draft saved. No credits deducted.','该笔课时已撤销':'Credit deduction reversed','修改记录':'Edit report','待完成记录':'Reports to complete','继续草稿':'Continue draft','填写记录':'Write report','已发布记录':'Published reports','还没有发布的课后记录。':'No published lesson reports yet.','老师完成课程后，学习内容、作业和反馈会出现在这里。':'Learning content, homework and feedback will appear here after the teacher completes a lesson.',
 '银行转账':'Bank transfer','现金':'Cash','刷卡':'Card','其他':'Other','赠课 / 无收款':'Complimentary / no payment','实际退款金额':'Actual refund','实际收款金额':'Amount received','填写实际退还给家长的金额。':'Enter the amount actually refunded to the parent.','赠课可填写 0；历史金额未知时不要猜测。':'Enter 0 for complimentary credits. Do not guess unknown historical amounts.','退款方式':'Refund method','收款方式':'Payment method','凭证号 / 转账备注（选填）':'Reference / transfer note (optional)','用于和银行或收款记录核对':'Reference for matching bank or payment records',
 '该学生没有可退的剩余课时。':'This student has no remaining credits to refund.','此处只记录已办理的退款，不会发起银行转账。':'This records a refund already arranged. It does not send a bank transfer.','退回课时':'Credits refunded','确认后将从剩余课时中扣除。':'These credits will be removed from the remaining balance.','退款日期':'Refund date','退款原因':'Refund reason','例如：学生搬家，退还剩余 5 课时费用。':'e.g. Student relocating; refund the remaining 5 credits.','确认记录退课退款':'Record withdrawal & refund','退课退款已记录，课时余额与对账明细已更新。':'Refund recorded. Credits and reconciliation have been updated.',
 '使用中':'Active','已停用':'Disabled','可管理学生、老师、排课、充值及退课退款。不能添加管理员或查看老板对账页。':'Can manage students, teachers, scheduling, top-ups and refunds. Cannot add administrators or access owner reconciliation.',
 '停用账号':'Disable account','恢复账号':'Enable account','还没有管理员，点击「添加管理员」开通账号。':'No administrators yet. Select “Add administrator” to create an account.','停用账号会立即退出其登录状态，历史记录和已排课程保留。':'Disabling an account ends its sessions. Existing records and scheduled lessons are preserved.',
 '停用管理员':'Disable administrator','恢复管理员':'Enable administrator','停用后无法登录，历史记录和课程仍会保留。':'The administrator will be unable to sign in. Existing records and lessons are preserved.','恢复后可以使用原手机号和密码登录。':'The original phone number and password will work again.','确认停用':'Confirm disable','确认恢复':'Confirm enable','账号状态已更新。':'Account status updated.',
 '管理员可处理日常教学和充值退款。老板的账目总结及管理员权限管理仍仅对你开放。':'Administrators handle daily teaching, top-ups and refunds. Only you can access owner reconciliation and manage administrators.','管理员姓名':'Administrator name','至少 10 位。请单独告知管理员，并让其登录后修改。':'At least 10 characters. Share privately and ask the administrator to change it after sign-in.','创建管理员':'Create administrator','管理员账号已创建。':'Administrator account created.',
 '每日':'Daily','每周':'Weekly','每月':'Monthly','汇总周期':'Reporting period','选择日期':'Select date','对账日期':'Reconciliation date','正在汇总账目…':'Loading reconciliation…','周一至周日':'Monday–Sunday','自然月':'Calendar month','单日':'Single day','上课耗课':'Lesson usage','充值纠错':'Top-up correction','退款纠错':'Refund correction','耗课撤销':'Usage reversal',
 '有':'There are','笔历史收款、退款或相关纠错未登记金额，以下金额汇总尚不完整。可在流水中补录；未登记金额不会被当作 0 元。':'historical cash transactions or corrections with missing amounts. Totals are incomplete. Add amounts from the transaction list; unknown amounts are not treated as zero.',
 '本期净收款':'Net receipts','收款 − 退款 ＋ 记账纠错':'Receipts − refunds + corrections','本期收款':'Receipts','本期退款':'Refunds','本期无充值课时':'No credits added in this period','期初课时':'Opening credits','耗课时':'Credits used','退课时':'Credits refunded','纠错净调整':'Net corrections','期末课时':'Closing credits','金额纠错：':'Cash corrections:','当前学生余额与课时流水一致。':'Current student balances match the credit ledger.','发现学生余额与流水不一致，请核查历史记录。':'Student balances do not match the ledger. Please review past records.','本页记录机构账目，银行到账仍需凭证核对。':'These are school records. Confirm actual bank payments against your receipts.',
 '每日汇总':'Daily breakdown','日期':'Date','收款 AUD':'Receipts AUD','退款 AUD':'Refunds AUD','金额纠错 AUD':'Corrections AUD','净收款 AUD':'Net receipts AUD','含未登记金额':'Includes missing amounts','本期流水明细':'Transactions in this period','业务日期 / 编号':'Business date / ID','金额变动':'Cash change','收付款方式':'Payment method','登记人 / 备注':'Recorded by / note','金额未登记':'Amount missing','补录':'Add amount','这个周期内暂无账目变动。':'No transactions in this period.',
 '按充值、上课和退款的业务日期汇总。补录会更新对应日期的统计；跨期撤销按撤销当天计入纠错，不直接删除原周期的记录。草稿、未来排课不计为耗课。':'Totals use the business date of top-ups, lessons and refunds. Backdated entries update that date. Reversals appear on their own date without removing the original period’s entry. Drafts and future lessons are not usage.',
 '补录历史金额':'Add a historical amount','只补录金额，不改变课时。请根据真实收款或退款凭证填写。':'Only the cash amount is added; credits stay unchanged. Use the actual receipt or refund record.','确认补录':'Confirm amount','历史金额已补录。':'Historical amount added.',
 '暂时无法连接':'Unable to connect','重新加载':'Reload','网络连接失败，请稍后重试。':'Connection failed. Please try again.','服务暂时不可用，请稍后重试。':'The service is unavailable. Please try again.','操作未完成。':'The action could not be completed.',
 '请先登录。':'Please sign in.','登录已过期，请重新登录。':'Your session has expired. Please sign in again.','页面已过期，请刷新后重试。':'The page is out of date. Refresh and try again.','手机号或密码不正确。':'The phone number or password is incorrect.','登录尝试过多，请 15 分钟后重试。':'Too many sign-in attempts. Try again in 15 minutes.','当前密码不正确。':'The current password is incorrect.','新密码需为 10–128 位。':'The new password must contain 10–128 characters.',
 '此功能仅限老板账号。':'This feature is restricted to the owner.','请选择有效的管理员，老板账号不能在这里停用。':'Select a valid administrator. Owner accounts cannot be disabled here.','账号状态无效。':'Invalid account status.','请选择日、周或月。':'Select daily, weekly or monthly.','只能补录充值或退款记录的金额。':'Only top-up or refund amounts can be added.','这笔记录已经登记金额，不能重复补录。':'An amount is already recorded for this transaction.',
 '请输入有效的澳元金额，最多两位小数，且不超过 1,000,000。':'Enter an AUD amount up to 1,000,000, with no more than two decimal places.','请选择收付款方式。':'Select a payment method.','凭证号或转账备注最多 100 个字。':'The reference must be 100 characters or fewer.','实际退款金额必须大于 0。':'The refund amount must be greater than zero.',
 '该手机号已有账号，请使用独立的管理员手机号。':'This phone is already registered. Use a separate administrator phone number.','该手机号已有账号，请使用独立的老师手机号。':'This phone is already registered. Use a separate teacher phone number.','初始密码需为 10–128 位。':'The initial password must contain 10–128 characters.','请输入完整手机号，可包含国家区号。':'Enter a full phone number, optionally including the country code.',
 '课时必须大于 0，最多保留两位小数，且不超过 10000。':'Credits must be greater than zero and no more than 10,000, with at most two decimal places.','剩余课时不足，无法完成此次操作。':'There are not enough remaining credits for this action.','学生不存在。':'Student not found.','此记录不能撤销。':'This transaction cannot be reversed.','此记录已撤销。':'This transaction has already been reversed.','记录已存在，请刷新后查看。':'This record already exists. Refresh to view it.','输入内容无效。':'Invalid input.','请求内容无效。':'Invalid request.','请求来源无效。':'Invalid request origin.','暂时无法完成操作，请稍后重试。':'The action is temporarily unavailable. Please try again.',
 '只有老师可以修改课时。':'Only authorised school staff can change credits.','只有管理员可以添加老师。':'Only administrators can add teachers.','只有管理员可以排课或调整课程。':'Only administrators can schedule or reschedule lessons.','只有管理员可以取消课程。':'Only administrators can cancel lessons.','只有管理员或任课老师可以填写课后记录。':'Only administrators or the assigned teacher can write lesson reports.',
 '无法访问这节课程。':'You do not have access to this lesson.','这节课已被更新，请刷新页面后再操作。':'This lesson has changed. Refresh before continuing.','请选择有效的上课日期和时间。':'Select a valid lesson date and time.','所选时间处于夏令时调整区间，请选择其他时间。':'This time does not exist due to daylight saving. Choose another time.','所选时间有夏令时歧义，请选择其他时间。':'This time is ambiguous due to daylight saving. Choose another time.',
 '只能修改尚未完成且未取消的课程。':'Only scheduled lessons can be changed.','操作编号无效，请重新打开排课表单。':'Invalid action ID. Reopen the scheduling form.','请选择有效的任课老师。':'Select an active teacher.','结束时间必须晚于开始时间，单次课程最长 12 小时。':'The end must be after the start. A lesson can last at most 12 hours.','每节课请选择 1–30 位学生。':'Select 1–30 students per lesson.','上课地点不能超过 150 个字。':'The location must be 150 characters or fewer.','这位老师在该时段已有课程，请调整时间或老师。':'This teacher already has a lesson at that time. Change the time or teacher.','所选学生不存在，请刷新后重试。':'A selected student no longer exists. Refresh and try again.',
 '只能取消未完成的课程。已完成的课时请通过账本撤销。':'Only scheduled lessons can be cancelled. Reverse completed deductions in the credit ledger.','已取消的课程不能填写或发布课后记录。':'Reports cannot be written or published for cancelled lessons.','课程尚未结束，可先保存草稿，结束后再确认完成。':'This lesson has not ended. Save a draft and complete it after the end time.','已完成课程请使用修改课后记录。':'Use Edit lesson report for a completed lesson.','课程尚未完成，请先填写并确认完成。':'The lesson is not completed. Write a report and confirm completion first.','请为这节课的每位学生填写记录。':'Provide a report for every student in this lesson.',
 '学习内容、今日作业和课后反馈各最多 2000 字。':'Learning content, homework and feedback must each be 2,000 characters or fewer.','请填写学习内容、今日作业和课后反馈；没有作业可填写“今日无作业”。':'Enter learning content, homework and feedback. Write “No homework” if none is assigned.','修改反馈不会改变课时。需要调整扣费请由管理员在账本中处理。':'Editing feedback does not change credits. Ask an administrator to correct deductions in the ledger.',
 '此手机号是老师账号，请使用家长手机号。':'This phone belongs to a staff account. Use a parent phone number.','新家长的初始密码需为 10–128 位。':'A new parent password must contain 10–128 characters.','操作编号无效，请刷新后重试。':'Invalid action ID. Refresh and retry.','记录类型无效。':'Invalid transaction type.','不能登记尚未发生的上课或充值记录。':'You cannot record a lesson or payment dated in the future.','备注不能超过 300 个字。':'Notes must be 300 characters or fewer.',
 '更新于':'Updated','课时余额':'Credit balance'
 };
 const patterns=[
 [/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · 新增排课$/,(_,time)=>`${time} · Schedule lesson`],
 [/^已安排 (\d+) 次课程，课时暂不扣除。$/,(_,n)=>`${n} lessons scheduled. No credits have been deducted.`],
 [/^(\d{4}-\d{2}-\d{2})：(.+)$/,(_,date,message)=>`${date}: ${window.translateUI(message)}`],

 [/^→ (扣除|充值)后 ([-\d,.]+) 课时$/,(_,kind,n)=>`→ ${n} credits after ${kind==='扣除'?'deduction':'top-up'}`],
  [/^按机构时间显示 · (.+)$/,(_,z)=>`School time · ${z}`],
  [/^时间以 (.+) 为准。排课不扣课时；完成课程并发布记录后才扣除。$/,(_,z)=>`Times use ${z}. Scheduling does not deduct credits; completion and publication do.`],
  [/^(.+) · 排课不会提前扣课时$/,(_,z)=>`${z} · No credits are deducted when scheduling`],
  [/^(.+) · (周一至周日|自然月|单日)$/,(_,z,p)=>`${z} · ${messages[p]}`],
  [/^([\d,.]+) 课时\/人$/,(_,n)=>`${n} credits / student`],
  [/^([−+\d,.]+) 课时$/,(_,n)=>`${n} credits`],
  [/^已扣 ([\d,.]+) 课时$/,(_,n)=>`${n} credits deducted`],
  [/^充值 ([\d,.]+) 课时$/,(_,n)=>`${n} credits added`],
  [/^退回 ([\d,.]+) 课时$/,(_,n)=>`${n} credits refunded`],
  [/^([\d,]+) 笔变动$/,(_,n)=>`${n} transactions`],
  [/^剩余 ([\d,.]+) 课时。支持部分或全部退课。$/,(_,n)=>`${n} credits remaining. Partial or full refunds are supported.`],
  [/^当前剩余 ([\d,.]+) 课时，支持 0.5 或自定义数值。$/,(_,n)=>`${n} credits remaining. Use 0.5 or a custom amount.`],
  [/^· 剩余 ([\d,.]+) 课时$/,(_,n)=>`· ${n} credits remaining`],
  [/^· 预计每人 ([\d,.]+) 课时$/,(_,n)=>`· ${n} planned credits per student`],
  [/^课时\s*→ (扣除|充值)后 ([-\d.]+) 课时$/,(_,kind,n)=>`credits → ${n} after ${kind==='扣除'?'deduction':'top-up'}`],
  [/^原记录：(退课退款|充值|扣除) ([\d,.]+) 课时。$/,(_,kind,n)=>`Original: ${kind==='充值'?'top-up':kind==='扣除'?'deduction':'refund'} of ${n} credits.`],
  [/^撤销后会(扣回|返还)相应课时，原记录仍会保留。涉及金额时会产生记账纠错，不代表实际收款或退款。$/,(_,kind)=>`Reversing will ${kind==='扣回'?'remove':'restore'} the credits and retain the original record. Cash entries are accounting corrections, not actual payments or refunds.`],
  [/^已纠错，参见 #(\d+)$/,(_,id)=>`Corrected; see #${id}`],
  [/^· 原记录 #(\d+)$/,(_,id)=>`· Original #${id}`],
  [/^更新于 (.+)$/,(_,when)=>`Updated ${when}`],
  [/^(.+)在该时段已有课程。$/,(_,name)=>`${name} already has a lesson at that time.`],
  [/^(.+)的剩余课时不足。本次尚未扣除任何学生的课时，可先保存草稿。$/,(_,name)=>`${name} has insufficient credits. No student has been charged. You can save a draft.`],
  [/^(.+)不能为空，且不能超过 (\d+) 个字。$/,(_,field,max)=>`${messages[field]||'This field'} is required and must be ${max} characters or fewer.`],
  [/^当前剩余$/,()=> 'Currently remaining'],[/^管理员 · (使用中|已停用)$/,(_,s)=>`Administrator · ${messages[s]}`],
  [/^\/　(.+)$/,(_,s)=>`/ ${messages[s]||s}`],
  [/^金额纠错：(.+)。(.+) 本页记录机构账目，银行到账仍需凭证核对。$/,(_,amount,status)=>`Cash corrections: ${amount}. ${messages[status]||status} Match payments against your bank receipts.`]
 ];
 window.uiLocale=(()=>{try{return localStorage.getItem('helens-language')==='en'?'en':'zh';}catch{return 'zh';}})();
 window.translateUI=text=>{
  if(window.uiLocale!=='en')return text;
  const trimmed=text.trim();
  let translated=messages[trimmed];
  if(!translated){for(const [pattern,replace] of patterns){if(pattern.test(trimmed)){translated=trimmed.replace(pattern,replace);break;}}}
  if(!translated)return text;
  return text.replace(trimmed,translated);
 };
 const originals=new WeakMap(),attrs=new WeakMap();
 const protectedSelector='[data-user-content],script,style,textarea,input,[data-language-control]';
 function translateNode(node){
  if(node.parentElement?.closest(protectedSelector))return;
  let saved=originals.get(node);
  if(!saved||node.nodeValue!==saved.last)saved={source:node.nodeValue,last:node.nodeValue};
  const output=window.translateUI(saved.source);
  if(output!==node.nodeValue)node.nodeValue=output;
  saved.last=output;originals.set(node,saved);
 }
 function controls(){
  if(!document.getElementById('language-control')){
   const button=document.createElement('button');button.id='language-control';button.className='language-floating';button.setAttribute('data-language-control','');document.body.append(button);
  }
  const head=document.querySelector('dialog[open] .modal-head');
  if(head&&!head.querySelector('[data-language-control]')){const button=document.createElement('button');button.type='button';button.className='language-inline';button.setAttribute('data-language-control','');head.insertBefore(button,head.querySelector('.close'));}
  document.querySelectorAll('[data-language-control]').forEach(button=>{const label=window.uiLocale==='en'?'中文':'English';if(button.textContent!==label)button.textContent=label;button.setAttribute('aria-label',window.uiLocale==='en'?'Switch to Chinese':'切换为英文');button.onclick=()=>{window.uiLocale=window.uiLocale==='en'?'zh':'en';try{localStorage.setItem('helens-language',window.uiLocale);}catch{}apply();};});
 }
 function apply(){
  observer.disconnect();
  document.documentElement.lang=window.uiLocale==='en'?'en':'zh-CN';
  document.title='HELEN’S MATH SECRETS · '+(window.uiLocale==='en'?'Learning portal':'教学管理');
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let node;while((node=walker.nextNode()))translateNode(node);
  document.querySelectorAll('[placeholder],[aria-label],[title]').forEach(el=>{
   if(el.closest('[data-user-content],[data-language-control]'))return;
   let record=attrs.get(el)||{};
   for(const attr of ['placeholder','aria-label','title'])if(el.hasAttribute(attr)){
    const value=el.getAttribute(attr);let saved=record[attr];if(!saved||value!==saved.last)saved={source:value,last:value};
    const output=window.translateUI(saved.source);if(value!==output)el.setAttribute(attr,output);saved.last=output;record[attr]=saved;
   }
   attrs.set(el,record);
  });
  controls();
  observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['open','placeholder','aria-label','title']});
 }
 const observer=new MutationObserver(apply);
 window.applyUILanguage=apply;
 apply();
})();
