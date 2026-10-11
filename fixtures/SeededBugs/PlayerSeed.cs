using UnityEngine;

namespace SeededBugs
{
    public class PlayerSeed : MonoBehaviour
    {
        [SerializeField] private float moveSpeed = 5f;
        [SerializeField] private Animator animator;

        private Vector2 input;

        private void Update()
        {
            input = new Vector2(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));

            Rigidbody2D body = GetComponent<Rigidbody2D>();
            body.MovePosition(body.position + input * moveSpeed);

            bool firing = Input.GetMouseButton(0);
            animator.SetBool("IsFire", firing);
        }
    }
}
